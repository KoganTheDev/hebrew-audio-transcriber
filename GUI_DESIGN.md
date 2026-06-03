# Modern Step-by-Step Wizard GUI - Design Document

## Overview
The Speech-to-Text application now features a **modern, interactive step-by-step wizard interface** that guides users through the transcription process in a clear, intuitive way.

## Key Features

### 1. **Step-by-Step Navigation**
- **6 Clear Steps** with visual progress indicator:
  1. 📁 **File Selection** - Choose your audio/video file
  2. 🧠 **Model Selection** - Pick the AI model
  3. ⚡ **Device Selection** - Choose processing device (CPU/GPU)
  4. ✓ **Review** - (Placeholder for future enhancements)
  5. ⏳ **Transcription** - Live progress monitoring
  6. ✅ **Completion** - Success screen with results

### 2. **Visual Progress Indicator**
- Circular step indicators at the top of the window
- Visual status for each step:
  - **Completed**: ✅ Green circle
  - **Current**: 🔵 Blue/Indigo circle
  - **Upcoming**: ⚪ Gray circle
- Connector lines between steps
- Step names and emojis for quick recognition

### 3. **Modern Design Elements**

#### Color Palette (Vibrant & Professional)
```
Primary Background:   #0F1419 (Very dark blue-gray)
Secondary Bg:         #1A1E27 (Darker blue-gray)
Tertiary Bg:          #2A2E37 (Medium dark)

Accent (Primary):     #6366F1 (Indigo)
Accent Hover:         #818CF8 (Light indigo)
Accent Dark:          #4F46E5 (Dark indigo)
Secondary Accent:     #EC4899 (Pink/Magenta)
Tertiary Accent:      #F59E0B (Amber)

Success:              #10B981 (Green)
Warning:              #F59E0B (Amber)
Error:                #EF4444 (Red)

Text Primary:         #F3F4F6 (Off-white)
Text Secondary:       #9CA3AF (Gray)
Text Tertiary:        #6B7280 (Dark gray)
```

#### Typography
- **Titles**: Segoe UI 20px Bold
- **Subtitles**: Segoe UI 12px Regular
- **Labels**: Segoe UI 11-13px
- **Body**: Segoe UI 10px Regular

#### Spacing & Borders
- Rounded corners: 14-16px (modern look)
- Padding: 20-32px (generous spacing)
- Borders: 1-2px (subtle definition)
- Smooth transitions and hover effects

### 4. **Interactive Wizard Steps**

#### **Step 1: File Selection**
- Large drag-and-drop zone with visual feedback
- Browse button for file picker
- File size display
- Supported formats list
- Success feedback when file selected

#### **Step 2: Model Selection**
- Radio buttons for each model
- Card-based layout for each model
- Model information:
  - Name and description
  - Speed indicator
  - RAM requirements
  - Accuracy score
  - "Recommended" badge for default model
- Recommended model pre-selected

#### **Step 3: Device Selection**
- System information card showing:
  - CPU cores count
  - RAM amount
  - Operating system
- Gradient background on system info (indigo → pink)
- CPU and GPU options
- GPU availability detection
- Performance badges ("⚡ Faster")

#### **Step 4: Transcription Progress**
- Real-time progress percentage
- Animated progress bar (gradient: indigo → pink)
- Status message updates
- Professional transcription screen

#### **Step 5: Completion**
- Large ✅ emoji success indicator
- Confirmation message
- Output file path display
- Option to start new transcription

### 5. **Navigation Controls**
- **Back Button**: Return to previous step (disabled on first step)
- **Next Button**: Proceed to next step with validation
- **Cancel Button**: Exit application (or cancel transcription)
- All buttons have hover/press states
- Clear, large buttons (44px height)

### 6. **Color Themes & Gradients**

#### Header
- Gradient: Indigo (#6366F1) → Pink (#EC4899)
- White text with subtitle in semi-transparent white

#### System Info Card
- Gradient: Indigo → Pink
- White text on semi-transparent overlays

#### Progress Bar
- Gradient: Indigo → Pink
- Smooth animation during transcription

#### Buttons
- Primary (Next): Indigo background, white text
- Secondary (Back): Transparent with indigo border, hover highlights
- Danger (Cancel): Red background, white text

### 7. **Modern UX Patterns**

✨ **Implemented Patterns:**
- Stepper/Wizard pattern for multi-step flows
- Card-based design for grouping related information
- Gradient overlays for visual hierarchy
- Emoji usage for quick visual recognition
- Large interactive targets (buttons 44px minimum)
- Generous whitespace and padding
- Clear visual feedback on interactions

### 8. **Responsive Design**
- Window size: 1000×900px (optimized for visibility)
- Scrollable content areas for longer lists
- Responsive button sizing
- Proper text wrapping for long content

## Technical Implementation

### New Classes
- `Step` - Enum for application steps
- `ModernStyleSheet` - Centralized style definitions
- `StepProgressIndicator` - Visual step indicator widget
- `FileSelectStep` - Step 1 implementation
- `ModelSelectStep` - Step 2 implementation
- `DeviceSelectStep` - Step 3 implementation
- `TranscriptionStep` - Progress monitoring
- `CompleteStep` - Completion screen

### File Modified
- [speech_to_text/gui/main_window.py](speech_to_text/gui/main_window.py) - Complete redesign from single-window to wizard pattern

## Usage

Run the application with:
```bash
python speech_to_text/main.py
```

Or from VS Code: Press **F5**

## Future Enhancements

Possible improvements:
1. **Step 4 Review**: Add a review screen before transcription
2. **Animations**: Smooth fade/slide transitions between steps
3. **Dark Mode Toggle**: Theme switching capability
4. **Saved Presets**: Save user preferences
5. **History**: Show past transcriptions
6. **Batch Processing**: Handle multiple files
7. **Advanced Settings**: More transcription options
8. **Keyboard Navigation**: Tab through steps, Enter to proceed

## Design Inspiration
Modern designs from:
- Slack (clean, vibrant color palette)
- Discord (dark mode, modern gradients)
- Figma (card-based UI, clear hierarchy)
- Vercel (gradient accents, professional typography)

---

**Version**: 1.0
**Last Updated**: May 25, 2026
**Status**: ✅ Fully Implemented
