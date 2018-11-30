import setuptools

AUTHOR = "Cacophony Project Developers"
AUTHOR_EMAIL = "dev@cacophony.org.nz"

long_description = """\
This is a server side component that runs alongside the Cacophony
Project API, performing post-upload processing tasks.
"""

setuptools.setup(
    name="cacophony-processing",
    version="0.5.0",
    author=AUTHOR,
    author_email=AUTHOR_EMAIL,
    maintainer=AUTHOR,
    maintainer_email=AUTHOR_EMAIL,
    description="Processing of Cacophony Project recordings",
    long_description=long_description,
    url="https://github.com/TheCacophonyProject/cacophony-processing",
    packages=setuptools.find_packages(),
    scripts=["audio_processing.py", "thermal_processing.py"],
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX :: Linux",
    ),
)
