#!/bin/bash
rm -rf dist/
rm -rf build/
rm -r /Applications/Vince.app
python setup.py py2app
cp -r dist/Vince.app /Applications/