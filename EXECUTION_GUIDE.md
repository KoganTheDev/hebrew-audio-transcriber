# How to Run the Speech-to-Text Transcriber

This document explains how to run the application from VS Code and the command line.

## ✅ Quick Start (Easiest Options)

### Option 1: From VS Code (Recommended)
1. Open this project in VS Code
2. Press **F5** or go to **Run → Start Debugging**
3. Select **"Speech-to-Text Transcriber"** from the dropdown
4. The app launches with full logging visible in the terminal

### Option 2: Double-click run.bat (Windows)
Simply double-click **`run.bat`** in the project root folder. A command window opens and runs the app automatically.

### Option 3: PowerShell
Run this in PowerShell from the project root:
```powershell
.\run.ps1
```

### Option 4: Command Line - Run main.py directly (Now Works!)
```bash
python speech_to_text/main.py
```
This now works thanks to automatic path resolution in main.py!

### Option 5: Command Line - Module mode
```bash
python -m speech_to_text.main
```

## ❌ What NOT to Do

**No workarounds needed!** The application now works from anywhere:
- ✅ `python speech_to_text/main.py` - Works!
- ✅ `python -m speech_to_text.main` - Works!
- ✅ `python -m speech_to_text` - Works!

## VS Code Configuration Details

The `.vscode/` folder contains:

### `launch.json`
Defines two run configurations:
1. **Speech-to-Text Transcriber** - Main app (press F5)
2. **Run Tests** - Test suite (select from dropdown, press F5)

### `settings.json`
- Configures Python path for module resolution
- Enables code formatting with Black
- Sets up linting

### `extensions.json`
Recommends useful Python extensions (VS Code will suggest installing them)

## Technical Details: How It Works Now

The ModuleNotFoundError has been solved with automatic path handling in `speech_to_text/main.py`:

```python
import sys
import os

# Ensure parent directory is in path so we can import speech_to_text package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

This code:
1. Gets the absolute path of main.py (`__file__`)
2. Gets the parent directory (speech_to_text/)
3. Gets the grandparent directory (project root)
4. Adds it to sys.path at the beginning

This allows Python to find and import the `speech_to_text` package regardless of how the script is executed.

## Debugging Tips

1. **View Logs**: The app writes detailed logs to `speech_to_text.log` in the project root
2. **Real-time Output**: Launch from VS Code to see logs in the integrated terminal
3. **Set Breakpoints**: With F5 launched, set breakpoints in any `.py` file
4. **Watch Variables**: Use VS Code's debugger watch panel

## Running Tests

### From VS Code
- Press F5 and select **"Run Tests"** from the dropdown

### From Command Line
```bash
python -m pytest tests/ -v
```

## Python Version
Requires Python 3.11 or higher.

## Environment Setup

The app auto-detects your environment:
- Python interpreter location (from virtual environment)
- Required packages (PyQt5, tqdm)
- Hardware capabilities (CPU cores, RAM, GPU)
- Operating system

All of this is logged on startup for debugging.

## Troubleshooting

### "ModuleNotFoundError: No module named 'speech_to_text'"
**FIXED!** This is automatically resolved now. The application's main.py includes automatic path handling that ensures the parent directory is added to Python's module search path.

If you still see this error:
1. Make sure you have the latest version of `speech_to_text/main.py` (should have path setup at the top)
2. Restart your terminal/IDE
3. Try running `python speech_to_text/main.py` directly

### "No module named 'PyQt5'"
**Solution**: Install requirements: `pip install -r requirements.txt`

### GUI doesn't appear
**Solution**: 
- Check the log output for errors
- Ensure you're using the F5 launcher in VS Code (not Ctrl+Shift+D)
- Try running from terminal to see full output

### Application hangs on startup
**Solution**: The app checks dependencies on startup. First run may take 5-10 seconds. Subsequent runs are faster (~3 seconds).

---

**Need Help?** Check `speech_to_text.log` for detailed error messages and execution flow.
