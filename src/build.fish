#!/bin/bash
rm -rf dist/
rm -rf build/
rm -r /Applications/vince.app
python setup.py py2app
mv dist/vince.app /Applications/