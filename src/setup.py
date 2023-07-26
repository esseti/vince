"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""

from setuptools import setup

APP = ['vince.py']
DATA_FILES = [('', ['credentials.json','icon.icns'])]

OPTIONS = {
           'argv_emulation': True, 
           'plist': {'LSUIElement': True,
                      'CFBundleName': 'Vince',
                      'CFBundleShortVersionString': '0.0.1', 
                      },
           'iconfile':'icon.png',
           }


setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
     author='Stefano Tranquillini',  # Set the author name here
    author_email='stefano.tranquillini@gmail.com',  # Set the author email here
    url='https://www.stefanotranquillini.com',  # Set the project URL here
    license='GNU GPL 3',  # Set the project license here
)
