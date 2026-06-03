"""
Allow running the package as a module: python -m speech_to_text
This delegates to the main.py entry point.
"""

from speech_to_text.main import main

if __name__ == "__main__":
    main()
