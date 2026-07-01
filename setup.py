"""Setup configuration for Speech-to-Text Transcriber."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="speech-to-text-transcriber",
    version="2.0.0",
    author="Development Team",
    author_email="dev@example.com",
    description="Professional GUI application for audio transcription using faster-whisper",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/example/speech-to-text",
    packages=find_packages(exclude=["tests", "docs", "*.egg-info"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Sound/Audio",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "speech-to-text=speech_to_text.main:main",
        ],
    },
    include_package_data=True,
    package_data={"speech_to_text": ["assets/*.ico"]},
    zip_safe=False,
)
