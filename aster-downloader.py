#!/usr/bin/env python3
"""
ASTER Data Downloader and Processor
Downloads ASTER DEM data from URLs, extracts zip files, 
keeps _dem.tif files and removes _num.tif files.

Uses NASA Earthdata Bearer token for authentication.
Get token at: https://urs.earthdata.nasa.gov -> Generate Token
"""

import os
import sys
import zipfile
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import time
import argparse
import logging
from typing import Optional, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('aster_download.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AsterDownloader:
    def __init__(self, output_dir: str = "data/aster30m",
                 max_workers: int = 4,
                 chunk_size: int = 8192,
                 max_retries: int = 3,
                 retry_delay: int = 5,
                 bearer_token: Optional[str] = None):
        """
        Initialize the ASTER downloader.

        Args:
            output_dir: Directory to save downloaded and extracted files
            max_workers: Number of parallel download threads
            chunk_size: Size of chunks for downloading files
            max_retries: Maximum number of retry attempts for failed downloads
            retry_delay: Delay in seconds between retry attempts
            bearer_token: NASA Earthdata Bearer token
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Store temp_zips at the parent level (e.g., data/temp_zips instead of data/aster30m/temp_zips)
        self.temp_dir = self.output_dir.parent / "temp_zips"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # DEM files go directly to the root output directory
        self.dem_dir = self.output_dir
        
        self.max_workers = max_workers
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Setup authentication
        self.bearer_token = self.load_token(bearer_token)
        
        # Create a session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.bearer_token}'
        })
        
        # Track progress
        self.downloaded_files = []
        self.failed_downloads = []
        self.processed_files = []
    
    def load_token(self, bearer_token: Optional[str]) -> str:
        """
        Load Bearer token from various sources.
        
        Args:
            bearer_token: Bearer token passed as argument
            
        Returns:
            Bearer token string
        """
        # Priority 1: Token passed as argument
        if bearer_token:
            logger.info("Using Bearer token from command line")
            return bearer_token
        
        # Priority 2: Token from token.txt file in script directory
        script_dir = Path(__file__).parent
        token_file = script_dir / "token.txt"
        
        if token_file.exists():
            try:
                with open(token_file, 'r') as f:
                    token = f.read().strip()
                    if token:
                        logger.info(f"Loaded Bearer token from {token_file}")
                        return token
            except Exception as e:
                logger.warning(f"Could not read token from {token_file}: {e}")
        
        # If no token found, prompt user
        print("\n" + "="*60)
        print("NASA Earthdata Bearer Token Required")
        print("="*60)
        print("To get a Bearer token:")
        print("1. Log in to: https://urs.earthdata.nasa.gov")
        print("2. Go to: Generate Token -> Generate Token")
        print("3. Copy the entire token string")
        print("")
        print("You can either:")
        print("- Save it to 'token.txt' in the same folder as this script")
        print("- Pass it via --token parameter")
        print("- Paste it below")
        print("="*60 + "\n")
        
        token = input("Enter your NASA Earthdata Bearer token: ").strip()
        
        # Offer to save token
        save = input("\nSave token to token.txt for future use? (y/n): ").lower().strip() == 'y'
        if save:
            try:
                with open(token_file, 'w') as f:
                    f.write(token)
                logger.info(f"Token saved to {token_file}")
            except Exception as e:
                logger.warning(f"Could not save token: {e}")
        
        return token
    
    def fetch_urls(self, url_source: str) -> List[str]:
        """
        Fetch URLs from the source (URL or local file).
        
        Args:
            url_source: URL or local file path containing the URLs
            
        Returns:
            List of URLs
        """
        urls = []
        
        try:
            # Check if it's a URL or local file
            if url_source.startswith(('http://', 'https://')):
                logger.info(f"Fetching URLs from: {url_source}")
                response = self.session.get(url_source, timeout=30)
                response.raise_for_status()
                content = response.text
            else:
                logger.info(f"Reading URLs from local file: {url_source}")
                with open(url_source, 'r') as f:
                    content = f.read()
            
            # Parse URLs
            urls = [line.strip() for line in content.split('\n') 
                   if line.strip() and line.strip().startswith('http')]
            
            logger.info(f"Found {len(urls)} URLs to process")
            return urls
            
        except Exception as e:
            logger.error(f"Error fetching URLs: {e}")
            sys.exit(1)
    
    def download_file(self, url: str) -> Tuple[str, bool]:
        """
        Download a single file with retry logic and Bearer token authentication.
        
        Args:
            url: URL of the file to download
            
        Returns:
            Tuple of (filename, success)
        """
        filename = url.split('/')[-1]
        filepath = self.temp_dir / filename
        
        # Skip if already downloaded
        if filepath.exists():
            logger.debug(f"File already exists, skipping: {filename}")
            return str(filepath), True
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Downloading {filename} (attempt {attempt + 1}/{self.max_retries})")
                
                # Create a new session for this download
                with requests.Session() as session:
                    session.headers.update({
                        'Authorization': f'Bearer {self.bearer_token}'
                    })
                    
                    # Download with redirects
                    response = session.get(
                        url, 
                        stream=True, 
                        timeout=60,
                        allow_redirects=True,
                        verify=True
                    )
                    
                    # Check for authentication issues
                    if 'urs.earthdata.nasa.gov/oauth/authorize' in response.url:
                        logger.error(f"Authentication failed - redirected to login page")
                        logger.error("Bearer token may be expired or invalid")
                        logger.error("Generate a new token at: https://urs.earthdata.nasa.gov")
                        return filename, False
                    
                    response.raise_for_status()
                    
                    # Verify we're getting actual data (not an HTML error page)
                    content_type = response.headers.get('content-type', '')
                    if 'html' in content_type.lower():
                        logger.error(f"Received HTML instead of file data for {filename}")
                        logger.error("Authentication may have failed")
                        return filename, False
                    
                    # Download with progress
                    total_size = int(response.headers.get('content-length', 0))
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=self.chunk_size):
                            if chunk:
                                f.write(chunk)
                    
                    # Verify the file is actually a zip
                    if filepath.stat().st_size < 1000:
                        with open(filepath, 'rb') as f:
                            header = f.read(4)
                            if header != b'PK\x03\x04':  # ZIP file header
                                logger.error(f"Downloaded file is not a valid ZIP: {filename}")
                                filepath.unlink()
                                return filename, False
                
                logger.info(f"Successfully downloaded: {filename}")
                return str(filepath), True
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401:
                    logger.error(f"Authentication failed (401) for {filename}")
                    logger.error("Bearer token is invalid or expired")
                    logger.error("Generate a new token at: https://urs.earthdata.nasa.gov")
                    return filename, False
                elif e.response.status_code == 403:
                    logger.error(f"Access forbidden (403) for {filename}")
                    logger.error("You may need to accept the ASTER data use agreement")
                    return filename, False
                else:
                    logger.warning(f"HTTP error {e.response.status_code} for {filename}: {e}")
            except Exception as e:
                logger.warning(f"Download failed for {filename}: {e}")
            
            if attempt < self.max_retries - 1:
                logger.info(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)
            else:
                logger.error(f"Failed after {self.max_retries} attempts: {filename}")
        
        return filename, False
    
    def process_zip(self, zip_path: str) -> Tuple[str, bool, List[str]]:
        """
        Extract zip file preserving folder structure, skip _num.tif files.

        Args:
            zip_path: Path to the zip file

        Returns:
            Tuple of (zip_filename, success, list_of_extracted_files)
        """
        zip_path = Path(zip_path)
        extracted_files = []

        if not zip_path.exists():
            logger.error(f"Zip file not found: {zip_path}")
            return str(zip_path), False, []

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # List all files in the zip
                file_list = zip_ref.namelist()

                for file_name in file_list:
                    # Skip _num.tif files
                    if file_name.endswith('_num.tif'):
                        logger.debug(f"Skipping NUM file: {file_name}")
                        continue

                    # Extract all other files preserving folder structure
                    target_path = self.dem_dir / file_name

                    # Create parent directories if needed
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    # Skip directories (they're created above)
                    if file_name.endswith('/'):
                        continue

                    # Extract file
                    with zip_ref.open(file_name) as source:
                        with open(target_path, 'wb') as target:
                            target.write(source.read())

                    extracted_files.append(str(target_path))
                    if file_name.endswith('_dem.tif'):
                        logger.debug(f"Extracted DEM file: {target_path}")
                    else:
                        logger.debug(f"Extracted file: {target_path}")

            logger.info(f"Processed {zip_path.name}: extracted {len(extracted_files)} files")
            return str(zip_path), True, extracted_files

        except Exception as e:
            logger.error(f"Error processing zip file {zip_path}: {e}")
            return str(zip_path), False, []
    
    def download_batch(self, urls: List[str], start_idx: int = 0, 
                      end_idx: Optional[int] = None) -> None:
        """
        Download and process a batch of URLs.
        
        Args:
            urls: List of URLs to download
            start_idx: Starting index in the URL list
            end_idx: Ending index in the URL list (None for all)
        """
        if end_idx is None:
            end_idx = len(urls)
        
        batch_urls = urls[start_idx:end_idx]
        logger.info(f"Processing batch: {len(batch_urls)} files (index {start_idx} to {end_idx})")
        
        # Download files in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit download tasks
            future_to_url = {
                executor.submit(self.download_file, url): url 
                for url in batch_urls
            }
            
            # Process completed downloads
            with tqdm(total=len(batch_urls), desc="Downloading") as pbar:
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        filepath, success = future.result()
                        if success:
                            self.downloaded_files.append(filepath)
                        else:
                            self.failed_downloads.append(url)
                    except Exception as e:
                        logger.error(f"Exception during download: {e}")
                        self.failed_downloads.append(url)
                    pbar.update(1)
        
        # Process downloaded zip files
        logger.info("Processing downloaded zip files...")
        with tqdm(total=len(self.downloaded_files), desc="Extracting") as pbar:
            for zip_file in self.downloaded_files:
                if zip_file not in self.processed_files:
                    _, success, dem_files = self.process_zip(zip_file)
                    if success:
                        self.processed_files.append(zip_file)
                pbar.update(1)
    
    def reprocess_existing(self) -> None:
        """
        Reprocess all existing zip files in the temp directory.
        """
        zip_files = list(self.temp_dir.glob("*.zip"))

        if not zip_files:
            logger.info("No zip files found in temp directory to reprocess")
            return

        logger.info(f"Found {len(zip_files)} zip files to reprocess")

        # Clear any existing extraction first (optional - you may want to keep this commented)
        # for item in self.dem_dir.iterdir():
        #     if item.is_dir():
        #         shutil.rmtree(item)

        # Process each zip file
        processed_count = 0
        failed_count = 0

        with tqdm(total=len(zip_files), desc="Reprocessing") as pbar:
            for zip_file in zip_files:
                _, success, extracted_files = self.process_zip(str(zip_file))
                if success:
                    processed_count += 1
                else:
                    failed_count += 1
                pbar.update(1)

        logger.info(f"Reprocessing complete: {processed_count} successful, {failed_count} failed")

        # Count total extracted files
        dem_files = list(self.dem_dir.glob("**/*_dem.tif"))
        total_files = sum(1 for _ in self.dem_dir.glob("**/*") if _.is_file())

        logger.info(f"Total files extracted: {total_files}")
        logger.info(f"Total DEM files: {len(dem_files)}")

    def cleanup_temp_files(self, delete_zips: bool = False) -> None:
        """
        Clean up temporary files.
        
        Args:
            delete_zips: Whether to delete downloaded zip files
        """
        if delete_zips:
            logger.info("Cleaning up temporary zip files...")
            for zip_file in self.temp_dir.glob("*.zip"):
                try:
                    zip_file.unlink()
                except Exception as e:
                    logger.warning(f"Could not delete {zip_file}: {e}")
    
    def print_summary(self) -> None:
        """Print download summary."""
        print("\n" + "="*50)
        print("DOWNLOAD SUMMARY")
        print("="*50)
        print(f"Total files downloaded: {len(self.downloaded_files)}")
        print(f"Total files processed: {len(self.processed_files)}")
        print(f"Failed downloads: {len(self.failed_downloads)}")

        if self.failed_downloads:
            print("\nFailed URLs:")
            for url in self.failed_downloads[:10]:  # Show first 10
                print(f"  - {url}")
            if len(self.failed_downloads) > 10:
                print(f"  ... and {len(self.failed_downloads) - 10} more")

        # Count DEM files recursively (in folders)
        dem_files = list(self.dem_dir.glob("**/*_dem.tif"))
        num_files = list(self.dem_dir.glob("**/*_num.tif"))
        all_files = sum(1 for _ in self.dem_dir.glob("**/*") if _.is_file())

        # Count folders
        folders = set()
        for f in self.dem_dir.glob("**/*"):
            if f.is_dir() and f != self.dem_dir and f != self.temp_dir:
                folders.add(f)

        print(f"\nExtracted content:")
        print(f"  Total folders: {len(folders)}")
        print(f"  Total files: {all_files}")
        print(f"  DEM files (*_dem.tif): {len(dem_files)}")
        if num_files:
            print(f"  NUM files (*_num.tif): {len(num_files)} (should be 0)")

        print(f"\nOutput directory: {self.output_dir.absolute()}")

        # If in test mode, show the extracted file
        if len(dem_files) == 1:
            print(f"Test file extracted: {dem_files[0].relative_to(self.output_dir)}")

        print("="*50)


def main():
    parser = argparse.ArgumentParser(
        description="Download and process ASTER DEM data"
    )
    parser.add_argument(
        '--url-source',
        default='https://www.opentopodata.org/datasets/aster30m_urls.txt',
        help='URL or local file containing ASTER URLs'
    )
    parser.add_argument(
        '--output-dir',
        default='data/aster30m',
        help='Output directory for downloaded files'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=4,
        help='Number of parallel download threads'
    )
    parser.add_argument(
        '--start',
        type=int,
        default=0,
        help='Start index for batch processing'
    )
    parser.add_argument(
        '--end',
        type=int,
        default=None,
        help='End index for batch processing (None for all)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: download only the first file to verify setup'
    )
    parser.add_argument(
        '--delete-zips',
        action='store_true',
        help='Delete zip files after extraction'
    )
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Retry previously failed downloads'
    )
    parser.add_argument(
        '--token',
        help='NASA Earthdata Bearer token (or save in token.txt)'
    )
    parser.add_argument(
        '--reprocess',
        action='store_true',
        help='Reprocess existing zip files in temp directory with updated extraction logic'
    )
    
    args = parser.parse_args()
    
    # Override settings for test mode
    if args.test:
        args.end = 1
        args.workers = 1
        logger.info("TEST MODE: Downloading only the first file")
        print("\n" + "="*60)
        print("TEST MODE ENABLED")
        print("="*60)
        print("Downloading only the first file to verify setup...")
        print("="*60 + "\n")
    
    # Create downloader instance
    downloader = AsterDownloader(
        output_dir=args.output_dir,
        max_workers=args.workers,
        bearer_token=args.token
    )

    # Handle reprocess mode
    if args.reprocess:
        logger.info("REPROCESS MODE: Reprocessing existing zip files")
        print("\n" + "="*60)
        print("REPROCESS MODE")
        print("="*60)
        print("Reprocessing existing zip files with updated extraction logic...")
        print("This will preserve folder structure and skip _num.tif files.")
        print("="*60 + "\n")

        try:
            downloader.reprocess_existing()
            downloader.print_summary()
        except KeyboardInterrupt:
            logger.info("\nReprocessing interrupted by user")
            downloader.print_summary()
            sys.exit(0)
        except Exception as e:
            logger.error(f"Unexpected error during reprocessing: {e}")
            sys.exit(1)

        # Exit after reprocessing
        sys.exit(0)

    # Fetch URLs
    urls = downloader.fetch_urls(args.url_source)

    if not urls:
        logger.error("No URLs found to process")
        sys.exit(1)

    try:
        # Download and process files
        downloader.download_batch(urls, args.start, args.end)
        
        # Retry failed downloads if requested
        if args.retry_failed and downloader.failed_downloads:
            logger.info(f"Retrying {len(downloader.failed_downloads)} failed downloads...")
            retry_urls = downloader.failed_downloads.copy()
            downloader.failed_downloads.clear()
            downloader.download_batch(retry_urls, 0, None)
        
        # Clean up if requested
        if args.delete_zips:
            downloader.cleanup_temp_files(delete_zips=True)
        
        # Print summary
        downloader.print_summary()
        
    except KeyboardInterrupt:
        logger.info("\nDownload interrupted by user")
        downloader.print_summary()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()