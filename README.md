# ASTER DEM Data Downloader

A Python script to download and process ASTER Global Digital Elevation Model (GDEM) data from NASA Earthdata. The script automatically downloads, extracts, and organizes ASTER 30m resolution DEM tiles.

## Features

- 🚀 **Parallel downloads** with configurable worker threads
- 🔄 **Resume capability** - automatically skips already downloaded files
- 📦 **Automatic extraction** - extracts DEM files and discards unnecessary files
- 🔐 **Bearer token authentication** - secure NASA Earthdata authentication
- 📊 **Progress tracking** - real-time progress bars and detailed logging
- 🧪 **Test mode** - verify setup with single file download
- 💾 **Efficient storage** - option to delete zip files after extraction

## Prerequisites

### 1. NASA Earthdata Account

You need a NASA Earthdata account to download ASTER data:

1. Register at: https://urs.earthdata.nasa.gov/users/new
2. Log in to your account
3. Generate a Bearer token:
   - Go to: https://urs.earthdata.nasa.gov
   - Navigate to: **Generate Token** → **Generate Token**
   - Copy the entire token string

### 2. Python Environment with uv

This project uses [uv](https://github.com/astral-sh/uv) for Python package management.

## Installation

### 1. Clone or Download the Script

```bash
# Create project directory
mkdir aster-downloader && cd aster-downloader

# Save the script as aster_downloader.py
```

### 2. Install Dependencies with uv

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install required packages
uv pip install requests tqdm
```

### 3. Configure Authentication

Create a `token.txt` file in the same directory as the script:

```bash
# Save your NASA Earthdata Bearer token
echo "YOUR_BEARER_TOKEN_HERE" > token.txt
```

**Note:** The token is a long JWT string starting with `eyJ...`

## Usage

### Basic Commands

#### Test Mode (Recommended First Step)
```bash
# Download only the first file to verify setup
uv run python aster_downloader.py --test
```

#### Download All Data
```bash
# Download all ~22,000 ASTER tiles (requires ~1TB storage)
uv run python aster_downloader.py
```

#### Download Specific Range
```bash
# Download files 100-200
uv run python aster_downloader.py --start 100 --end 200
```

#### Batch Download Examples
```bash
# First 1000 files with 8 parallel workers
uv run python aster_downloader.py --start 0 --end 1000 --workers 8

# Download and delete zips after extraction (saves space)
uv run python aster_downloader.py --delete-zips
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--test` | False | Test mode: downloads only the first file |
| `--start` | 0 | Starting index in the URL list |
| `--end` | None | Ending index (None = all files) |
| `--workers` | 4 | Number of parallel download threads |
| `--output-dir` | `data/aster30m` | Output directory for files |
| `--delete-zips` | False | Delete zip files after extraction |
| `--retry-failed` | False | Retry failed downloads |
| `--token` | None | Bearer token (overrides token.txt) |
| `--url-source` | (NASA URL) | Source of ASTER URLs |

## Directory Structure

```
aster-downloader/
├── aster_downloader.py     # Main script
├── token.txt               # Your NASA Earthdata Bearer token
├── aster_download.log      # Detailed log file
├── requirements.txt        # Python dependencies (optional)
└── data/
    └── aster30m/
        ├── ASTGTMV003_*_dem.tif    # Extracted DEM files
        └── temp_zips/               # Downloaded zip files
            └── ASTGTMV003_*.zip
```

## File Processing

The script processes ASTER data files as follows:

1. **Downloads** `.zip` files from NASA Earthdata
2. **Extracts** `*_dem.tif` files (Digital Elevation Model)
3. **Ignores** `*_num.tif` files (QA/pixel count files)
4. **Saves** DEM files directly to `data/aster30m/`

## Resume Capability

The script automatically resumes interrupted downloads:

- ✅ **Skips** already downloaded zip files
- ✅ **Safe** to interrupt with `Ctrl+C`
- ✅ **Restart** anytime to continue where you left off

```bash
# Example: Resume after interruption
uv run python aster_downloader.py --start 0 --end 1000
# Interrupt with Ctrl+C after downloading 500 files
# Resume:
uv run python aster_downloader.py --start 0 --end 1000
# Will skip first 500 and continue from 501
```

## Storage Requirements

- **Each zip file**: ~25-30 MB
- **Each DEM file**: ~25 MB after extraction
- **Full dataset**: ~22,000 files ≈ 500-600 GB
- **With zips kept**: ~1 TB total
- **With `--delete-zips`**: ~500 GB total

## Performance Tips

### Optimize Download Speed
```bash
# Increase parallel workers for faster downloads
uv run python aster_downloader.py --workers 8

# For very fast connections
uv run python aster_downloader.py --workers 16
```

### Save Storage Space
```bash
# Delete zips after extraction
uv run python aster_downloader.py --delete-zips

# Process in smaller batches
uv run python aster_downloader.py --start 0 --end 1000 --delete-zips
uv run python aster_downloader.py --start 1000 --end 2000 --delete-zips
```

### Monitor Progress
```bash
# Watch the log file in real-time (in another terminal)
tail -f aster_download.log
```

## Troubleshooting

### Authentication Failed
- **Issue**: 401 Unauthorized error
- **Solution**: 
  1. Regenerate token at https://urs.earthdata.nasa.gov
  2. Update `token.txt` with new token
  3. Tokens expire after ~90 days

### Download Interruptions
- **Issue**: Network timeout or connection errors
- **Solution**: 
  - Script automatically retries 3 times
  - Use `--retry-failed` to retry all failed downloads
  - Check `aster_download.log` for specific errors

### Disk Space Issues
- **Issue**: Running out of storage
- **Solution**:
  - Use `--delete-zips` flag
  - Process in smaller batches
  - Check available space: `df -h data/aster30m`

### Slow Downloads
- **Issue**: Downloads taking too long
- **Solution**:
  - Increase workers: `--workers 8`
  - Check network speed
  - Consider downloading during off-peak hours

## Examples for Common Use Cases

### Download Specific Geographic Region
Since ASTER files are named by coordinates (e.g., `N00E006` = 0°N, 6°E):
1. First, download the URL list
2. Filter for your region
3. Create a custom URL file

```bash
# Download URL list
curl -O https://www.opentopodata.org/datasets/aster30m_urls.txt

# Filter for specific region (example: Africa, 20°S-20°N, 10°W-50°E)
grep -E "N[0-1][0-9]E[0-4][0-9]|S[0-1][0-9]E[0-4][0-9]" aster30m_urls.txt > africa_urls.txt

# Use custom URL file
uv run python aster_downloader.py --url-source africa_urls.txt
```

### Production Download Strategy
```bash
# 1. Test setup
uv run python aster_downloader.py --test

# 2. Download first batch to estimate time/space
uv run python aster_downloader.py --start 0 --end 100

# 3. Download in 5000-file batches with cleanup
for i in 0 5000 10000 15000 20000; do
    uv run python aster_downloader.py --start $i --end $((i+5000)) --workers 8 --delete-zips
done
```

## Data Information

### ASTER GDEM Version 3
- **Resolution**: 30 meters
- **Coverage**: 83°N to 83°S
- **Tile Size**: 1° x 1° (3601 x 3601 pixels)
- **Datum**: WGS84
- **Format**: GeoTIFF
- **Units**: Meters above sea level

### File Naming Convention
- `ASTGTMV003_N00E006_dem.tif`
  - `ASTGTMV003`: ASTER GDEM Version 3
  - `N00E006`: Coordinates (0° North, 6° East)
  - `_dem`: Digital Elevation Model
  - `.tif`: GeoTIFF format

## License and Citation

ASTER GDEM is a product of METI and NASA. When using this data, please cite:

> NASA/METI/AIST/Japan Spacesystems and U.S./Japan ASTER Science Team (2019). 
> ASTER Global Digital Elevation Model Version 3 [Data set]. 
> NASA EOSDIS Land Processes DAAC. 
> https://doi.org/10.5067/ASTER/ASTGTM.003

## Support

For issues related to:
- **This script**: Check the logs in `aster_download.log`
- **NASA Earthdata**: https://urs.earthdata.nasa.gov/documentation
- **ASTER Data**: https://lpdaac.usgs.gov/products/astgtmv003/

## Contributing

Feel free to submit issues or pull requests for improvements.

## Acknowledgments

- NASA Earthdata for providing ASTER GDEM data
- USGS LP DAAC for data hosting
- The uv project for Python package management