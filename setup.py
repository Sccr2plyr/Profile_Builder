"""Setup script for Profile Builder."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="profile-builder",
    version="2.0.0",
    author="Profile Builder Team",
    description="Waveform profile builder for Raspberry Pi Pico testing",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Sccr2plyr/Profile_Builder",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "profile-builder=pc_app.waveform_profile_builder:main",
        ],
    },
    include_package_data=True,
    package_data={
        "pc_app": ["*.py"],
    },
)
