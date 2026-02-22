clear && PYTHON_EXECUTABLE=/opt/homebrew/Caskroom/miniforge/base/bin/python gtimeout 1800 python -m pytest -xvs --langs ${1:-rust,swift,go,python} --clear 2>&1 | tee test.log
