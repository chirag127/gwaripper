import setuptools

with open("README.md", "r", encoding="UTF-8") as fh:
    long_description = fh.read()


setuptools.setup(
    name="GWARipper",
    version="0.3",
    description="A script that rips and downloads audio files from the gonewildaudio subreddit.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    author="nilfoer",
    author_email="",
    license="MIT",
    keywords="script reddit gonewildaudio download scraping",
    packages=setuptools.find_packages(exclude=['tests*']),
    python_requires='>=3.6',
    install_requires=["pyperclip>=1.5.25,<=1.7.0", "praw==6", "beautifulsoup4>=4.5.3,<=4.6.3"],
    tests_require=['pytest'],
    # non-python data that should be included in the pkg
    # mapping from package name to a list of relative path names that should be
    # copied into the package
    package_data={},
    entry_points={
        'console_scripts': [
            # linking the executable gwaripper here to running the python
            # function main in the gwaripper module
            'gwaripper=gwaripper.cli:main',
            'gwaripper_webGUI=webGUI.start_webgui:main',
        ]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
