# Architecture Guide

## System Design

The Speech-to-Text Transcriber follows a layered architecture with clean separation of concerns:

### Architecture Layers

```
┌─────────────────────────────────────┐
│    GUI Layer (PyQt5)                │
│  - Main Window                      │
│  - User Interactions                │
│  - Progress Display                 │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│    Application Layer                │
│  - Main Entry Point                 │
│  - Configuration                    │
│  - Dependency Management            │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│    Business Logic Layer             │
│  - Transcriber                      │
│  - Hardware Detection               │
│  - Audio Processing                 │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│    External Dependencies            │
│  - faster-whisper                   │
│  - PyQt5                            │
│  - psutil                           │
└─────────────────────────────────────┘
```

## Module Responsibilities

### 1. Core Modules (`speech_to_text/core/`)

#### `dependencies.py`
- **Responsibility**: Manage external package dependencies
- **Functions**:
  - `ensure_dependencies(packages: Dict[str,str]) -> bool`
- **Behavior**: Check if packages are installed; auto-install missing ones
- **Error Handling**: Catches import errors and pip installation failures

#### `transcriber.py`
- **Responsibility**: Handle audio transcription
- **Class**: `Transcriber`
- **Key Methods**:
  - `load_model()` - Initialize WhisperModel
  - `transcribe(audio_file)` - Process audio and return text
  - `format_output(text)` - Format output with sentence breaks
- **Threading**: Supports progress callbacks for UI updates

### 2. Hardware Detection (`speech_to_text/`)

#### `hardware_detection.py`
- **Responsibility**: Detect system capabilities and optimize settings
- **Class**: `HardwareDetector`
- **Key Methods**:
  - `__init__()` - Auto-detect CPU, RAM, GPU
  - `_detect_gpu()` - Check for NVIDIA GPU via nvidia-smi
  - `get_device_recommendation()` - Suggest CPU/GPU
  - `estimate_time(duration, model, device)` - Calculate processing time
  - `can_run_model(model_size)` - Validate RAM requirements
  - `get_hardware_info()` - Return hardware dictionary

### 3. Configuration (`speech_to_text/`)

#### `config.py`
- **Responsibility**: Centralize all configuration
- **Contains**:
  - Application metadata (name, version)
  - Model definitions (5 Whisper models with metadata)
  - Default settings (language, beam size, etc.)
  - Required packages list
  - Output settings

### 4. GUI Layer (`speech_to_text/gui/`)

#### `main_window.py`
- **Responsibility**: Provide user interface
- **Classes**:
  - `TranscriptionThread` - Worker thread for transcription
  - `MainWindow` - Main GUI window
- **Features**:
  - File browser
  - Hardware information display
  - Model selection with pros/cons
  - Device selection (CPU/GPU)
  - Time estimation
  - Progress tracking
  - Error handling

### 5. Application Entry Point (`speech_to_text/`)

#### `main.py`
- **Responsibility**: Initialize and launch application
- **Flow**:
  1. Check dependencies
  2. Create QApplication
  3. Create MainWindow
  4. Show window and run event loop

## Data Flow

### Transcription Workflow

```
User selects audio file
        ↓
MainWindow validates file
        ↓
TranscriptionThread starts
        ↓
Transcriber.load_model()
        ↓
Transcriber.transcribe(audio_file)
        ↓
Progress callbacks emit updates
        ↓
Transcriber.format_output(text)
        ↓
Result displayed in GUI
        ↓
Output saved to file
```

## Design Patterns

### 1. Singleton Pattern
- `HardwareDetector` - Single instance per application
- Cached hardware info to avoid repeated detection

### 2. Factory Pattern
- Model loading based on configuration
- Device selection (CPU/GPU)

### 3. Observer Pattern
- Progress callbacks in Transcriber
- Qt signals/slots in GUI

### 4. Strategy Pattern
- Different output formats
- Device-specific transcription parameters

## Testing Strategy

### Unit Tests
- Test individual components in isolation
- Mock external dependencies (faster-whisper, psutil)
- 100% coverage for config, 86% for transcriber

### Integration Tests
- Test component interactions
- Validate end-to-end workflows
- Test configuration with hardware detection

### Coverage Breakdown
- `config.py`: 100%
- `dependencies.py`: 85%
- `transcriber.py`: 86%
- `hardware_detection.py`: 71%
- `gui/main_window.py`: 15% (complex PyQt5 GUI)

## Extensibility

### Adding New Features

1. **New Output Format**:
   - Add method to `Transcriber.format_output()`
   - Add option to `config.py`
   - Test in `test_transcriber.py`

2. **New Language Support**:
   - Add to config.LANGUAGE or make configurable
   - Test with different language models

3. **New Model**:
   - Add to MODELS dictionary in `config.py`
   - Update time estimation logic

4. **New Device Support**:
   - Extend `HardwareDetector._detect_gpu()`
   - Add device option to GUI

## Performance Considerations

### Time Estimation Formula
```
estimated_minutes = base_time * (audio_duration_minutes / 60)

where:
- base_time = model's time to process 1 hour of audio
- audio_duration_minutes = length of input file
```

### Memory Optimization
- Use int8 quantization on CPU
- GPU acceleration when available
- Streaming for large files

### UI Responsiveness
- Transcription runs in background thread
- Progress callbacks update UI without blocking
- Cancel operation via thread flag
