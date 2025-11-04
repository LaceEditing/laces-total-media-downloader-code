#!/usr/bin/env python3
"""
Setup script to build only the _tkinter extension module from Python source.
This builds the C extension against the Tcl/Tk libraries in /app/lib.
"""

from distutils.core import setup, Extension
import os
import sys

# Paths to Tcl/Tk in the Flatpak environment
tcl_tk_prefix = '/app'
tcl_tk_lib = os.path.join(tcl_tk_prefix, 'lib')
tcl_tk_include = os.path.join(tcl_tk_prefix, 'include')

# Find Tcl and Tk versions
tcl_version = '8.6'
tk_version = '8.6'

# Build the _tkinter extension module
tkinter_ext = Extension(
    '_tkinter',
    sources=[
        'Modules/_tkinter.c',
        'Modules/tkappinit.c'
    ],
    define_macros=[
        ('WITH_APPINIT', 1),
        ('TCL_THREADS', 1),
    ],
    include_dirs=[
        tcl_tk_include,
        os.path.join(tcl_tk_include, 'tcl' + tcl_version),
        os.path.join(tcl_tk_include, 'tk' + tk_version),
    ],
    library_dirs=[
        tcl_tk_lib,
    ],
    libraries=[
        'tcl' + tcl_version,
        'tk' + tk_version,
    ],
    runtime_library_dirs=[
        tcl_tk_lib,
    ],
)

setup(
    name='tkinter',
    version='3.11.13',
    description='Python interface to Tcl/Tk',
    ext_modules=[tkinter_ext],
    # Include the tkinter pure Python package
    packages=['tkinter'],
    package_dir={'tkinter': 'Lib/tkinter'},
)
