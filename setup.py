#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

####################### Licensing #######################################################
#
# Create Pull Requests, Installer
# Copyright (C) 2019 Evandro Coan <https://github.com/evandrocoan>
#
#  Redistributions of source code must retain the above
#  copyright notice, this list of conditions and the
#  following disclaimer.
#
#  Redistributions in binary form must reproduce the above
#  copyright notice, this list of conditions and the following
#  disclaimer in the documentation and/or other materials
#  provided with the distribution.
#
#  Neither the name Evandro Coan nor the names of any
#  contributors may be used to endorse or promote products
#  derived from this software without specific prior written
#  permission.
#
#  This program is free software; you can redistribute it and/or modify it
#  under the terms of the GNU General Public License as published by the
#  Free Software Foundation; either version 3 of the License, or ( at
#  your option ) any later version.
#
#  This program is distributed in the hope that it will be useful, but
#  WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################################
#

import sys

# https://setuptools.readthedocs.io/en/latest/setuptools.html
from setuptools import setup

#
# Release process setup see:
# https://github.com/pypa/twine
#
# Run pip install --user keyring
#
# Run on cmd.exe and then type your password when prompted
# keyring set https://upload.pypi.org/legacy/ your-username
#
# Run this to build the `dist/PACKAGE_NAME-xxx.tar.gz` file
#     rm -r ./dist && python setup.py sdist
#
# Run this to build & upload it to `pypi`, type addons_zz when prompted.
#     twine upload dist/*
#
# All in one command:
#     rm -rf ./dist && python3 setup.py sdist && twine upload dist/* && rm -rf ./dist
#
version = '0.1.0'

install_requires=[
    'six',
    'debug_tools',
    'PyGithub',
]

setup \
(
    name='githubpullrequests',
    version = version,
    description = 'Create Pull Requests, using GitHub API and a list of repositories',
    author = 'Evandro Coan',
    license = "GPLv3",
    url = 'https://github.com/evandrocoan/githubpullrequests',

    package_dir = {
        '': 'source',
    },

    # https://stackoverflow.com/questions/27784271/how-can-i-use-setuptools-to-generate-a-console-scripts-entry-point-which-calls
    entry_points = {
        "console_scripts": [
            "githubpullrequests = githubpullrequests.__init__:main",
        ],
    },

    packages = [
        'githubpullrequests',
    ],

    data_files = [
        ("", ["LICENSE.txt"]),
    ],

    install_requires = install_requires,
    long_description = open('README.md').read(),
    long_description_content_type='text/markdown',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
