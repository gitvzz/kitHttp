from setuptools import find_packages, setup

setup(
    name="kitHttp",
    version="0.1.0",
    packages=find_packages(),
    description="kitHttp",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    install_requires=["aiohttp==3.11.11"],
)
