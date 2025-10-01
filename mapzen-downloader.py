#!/usr/bin/env python3
"""
Batch setup script for Mapzen elevation data in OpenTopoData
Extracts .hgt.gz files in batches with resume capability

To download the files:

aws s3 cp --no-sign-request --recursive s3://elevation-tiles-prod/skadi ./data/mapzen
"""

import os
import gzip
import shutil
from pathlib import Path
import concurrent.futures
import time
import signal
import sys

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    print("\n\nGracefully stopping... (Press Ctrl+C again to force quit)")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)

def extract_gz_file(gz_path):
    """Extract a single .gz file"""
    output_path = gz_path.with_suffix('')  # Remove .gz extension

    # Skip if already extracted
    if output_path.exists():
        # Remove the .gz file if extraction already done
        if gz_path.exists():
            gz_path.unlink()
        return True, f"Already extracted: {output_path.name}"

    try:
        with gzip.open(gz_path, 'rb') as f_in:
            with open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove the .gz file after successful extraction
        gz_path.unlink()
        return True, str(gz_path)
    except Exception as e:
        return False, f"{gz_path}: {str(e)}"

def process_batch(gz_files_batch, batch_num, total_batches):
    """Process a batch of files"""
    print(f"\nProcessing batch {batch_num}/{total_batches} ({len(gz_files_batch)} files)")

    max_workers = min(8, os.cpu_count() or 1)
    successful = 0
    failed = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(extract_gz_file, gz_file): gz_file
                  for gz_file in gz_files_batch}

        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if shutdown_requested:
                print("\nShutdown requested, cancelling remaining tasks...")
                for f in futures:
                    f.cancel()
                break

            success, result = future.result()
            if success:
                successful += 1
            else:
                failed.append(result)

            # Progress indicator
            if (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{len(gz_files_batch)} files in batch {batch_num}")

    return successful, failed

def main():
    # Set up paths
    data_dir = Path("data/mapzen")

    if not data_dir.exists():
        print(f"Error: {data_dir} directory not found!")
        return

    # Find all .hgt.gz files
    print("Scanning for .hgt.gz files...")
    gz_files = list(data_dir.rglob("*.hgt.gz"))

    # Check already extracted files
    hgt_files = list(data_dir.rglob("*.hgt"))

    total_expected = 65341  # Total files in complete Mapzen dataset
    progress_percent = (len(hgt_files) / total_expected) * 100 if total_expected > 0 else 0

    print(f"\n📊 CURRENT STATUS:")
    print(f"  Already extracted: {len(hgt_files):,} files ({progress_percent:.1f}%)")
    print(f"  Remaining to extract: {len(gz_files):,} files")
    print(f"  Total expected: {total_expected:,} files")

    if not gz_files:
        print("\nAll files appear to be extracted already!")

        # Calculate total size
        print("\nCalculating total data size...")
        total_size = sum(f.stat().st_size for f in data_dir.rglob("*.hgt"))
        print(f"Total uncompressed data size: {total_size / (1024**3):.2f} GB")

        print("\n" + "="*50)
        print("SETUP COMPLETE! Next steps:")
        print("="*50)
        print("1. Update config.yaml to add the Mapzen dataset:")
        print("   datasets:")
        print("   - name: mapzen")
        print("     path: data/mapzen/")
        print("\n2. Restart the Docker container:")
        print("   docker restart opentopodata")
        print("\n3. Test the endpoint:")
        print("   curl 'http://localhost:5000/v1/mapzen?locations=40.7128,-74.0060'")
        print("="*50)
        return

    # Process in batches
    batch_size = 1000
    total_batches = (len(gz_files) + batch_size - 1) // batch_size

    print(f"\nWill process in {total_batches} batches of up to {batch_size} files each")
    print("You can stop this script anytime with Ctrl+C and resume later\n")

    total_successful = 0
    total_failed = []

    for batch_num in range(1, total_batches + 1):
        if shutdown_requested:
            break

        start_idx = (batch_num - 1) * batch_size
        end_idx = min(start_idx + batch_size, len(gz_files))
        batch = gz_files[start_idx:end_idx]

        successful, failed = process_batch(batch, batch_num, total_batches)
        total_successful += successful
        total_failed.extend(failed)

        # Small delay between batches
        if batch_num < total_batches and not shutdown_requested:
            time.sleep(1)

    # Print summary
    print(f"\n{'='*50}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'='*50}")
    print(f"✓ Successfully extracted: {total_successful} files")
    if total_failed:
        print(f"✗ Failed to extract: {len(total_failed)} files")
        for error in total_failed[:5]:
            print(f"  - {error}")
        if len(total_failed) > 5:
            print(f"  ... and {len(total_failed) - 5} more")

    # Count remaining work
    remaining_gz = list(data_dir.rglob("*.hgt.gz"))
    if remaining_gz:
        print(f"\n⚠ {len(remaining_gz)} files still need extraction")
        print("  Run this script again to continue")
    else:
        print("\n✓ All files have been extracted!")

        # Calculate total size
        print("\nCalculating total data size...")
        total_size = sum(f.stat().st_size for f in data_dir.rglob("*.hgt"))
        print(f"Total uncompressed data size: {total_size / (1024**3):.2f} GB")

    if shutdown_requested:
        print("\n⚠ Script was interrupted. Run again to continue extraction.")

    print(f"\n{'='*50}")
    print("NEXT STEPS:")
    print(f"{'='*50}")
    if not remaining_gz:
        print("1. Update config.yaml to add the Mapzen dataset:")
        print("   datasets:")
        print("   - name: mapzen")
        print("     path: data/mapzen/")
        print("\n2. Restart the Docker container:")
        print("   docker restart opentopodata")
        print("\n3. Test the endpoint:")
        print("   curl 'http://localhost:5000/v1/mapzen?locations=40.7128,-74.0060'")
    else:
        print("1. Run this script again to continue extraction:")
        print("   python3 setup_mapzen_batch.py")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()