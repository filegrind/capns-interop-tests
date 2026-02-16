clear && PYTHON_EXECUTABLE=/opt/homebrew/Caskroom/miniforge/base/bin/python python -m pytest -xvs --langs ${1:-rust,swift,go,python} --clear 2>&1 | tee test.log
