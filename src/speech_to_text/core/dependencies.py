"""
Dependency Management Module
Automatically installs required packages.
"""

import sys
import subprocess
import logging
from typing import Dict

from speech_to_text import config

logger = logging.getLogger(__name__)


def ensure_dependencies(packages: Dict[str, str]) -> bool:
    """
    Check and install required packages.
    
    Args:
        packages: Dict of {import_name: pip_name}
        
    Returns:
        True if all dependencies available, False otherwise
    """
    logger.info(f"Checking {len(packages)} required packages...")
    missing = []
    
    for import_name, pip_name in packages.items():
        try:
            __import__(import_name)
            logger.debug(f"✓ Package available: {import_name}")
        except ImportError:
            logger.warning(f"✗ Package missing: {import_name} (pip: {pip_name})")
            missing.append(pip_name)
    
    if not missing:
        logger.info("All required packages are available")
        return True
    
    logger.warning(f"{len(missing)} missing package(s) will be installed: {missing}")
    
    for package in missing:
        logger.info(f"Installing package: {package}")
        try:
            # Use subprocess with timeout and proper output redirection
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package, "-q"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=config.INSTALL_TIMEOUT_SECONDS,
                check=True
            )
            logger.info(f"✓ Successfully installed: {package}")
        except subprocess.TimeoutExpired:
            logger.error(f"✗ Installation timeout for {package} (exceeded {config.INSTALL_TIMEOUT_SECONDS}s)")
            logger.info(f"Please install manually: pip install {package}")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"✗ Installation failed for {package}")
            logger.debug(f"Return code: {e.returncode}")
            if e.stderr:
                logger.debug(f"Error output: {e.stderr.decode()}")
            logger.info(f"Please install manually: pip install {package}")
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error installing {package}: {e}", exc_info=True)
            return False
    
    logger.info(f"✓ All {len(missing)} missing package(s) installed successfully")
    return True
