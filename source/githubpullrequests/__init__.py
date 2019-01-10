#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

####################### Licensing #######################################################
#
# Create Pull Requests, using GitHub API and a list of repositories
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

import os
import io
import re

import github
import argparse

try:
    import configparser

except( ImportError, ValueError ):
    from six.moves import configparser

from debug_tools import getLogger
from debug_tools.utilities import wrap_text
from debug_tools.estimated_time_left import sequence_timer
from debug_tools.estimated_time_left import progress_info

log = getLogger( 127, __name__ )


def main():
    github_token = os.environ.get( 'GITHUBPULLREQUESTS_TOKEN', "" )
    gitmodules_files = []
    maximum_repositories = 0

    # https://stackoverflow.com/questions/6382804/how-to-use-getopt-optarg-in-python-how-to-shift
    argumentParser = argparse.ArgumentParser( description='Create Pull Requests, using GitHub API and a list of repositories' )

    argumentParser.add_argument( "-f", "--file", action="append",
            help="The file with the repositories informations" )

    argumentParser.add_argument( "-t", "--token", action="store",
            help="GitHub token with `public_repos` access" )

    argumentParser.add_argument( "-mr", "--maximum-repositories", action="store", type=int,
            help="The maximum count of repositories/requests to process per file." )

    argumentsNamespace = argumentParser.parse_args()
    # log( 1, argumentsNamespace )

    if argumentsNamespace.token:
        github_token = argumentsNamespace.token

    if argumentsNamespace.maximum_repositories:
        maximum_repositories = argumentsNamespace.maximum_repositories

    if argumentsNamespace.file:
        gitmodules_files = argumentsNamespace.file

    else:
        log.clean( "Error: Missing required command line argument `-f/--file`" )
        argumentParser.print_help()
        return

    pull_requester = PullRequester( github_token, maximum_repositories )
    for file in gitmodules_files:
        pull_requester.parse_gitmodules( file )

    pull_requester.publish_report()


class PullRequester(object):

    def __init__(self, github_token, maximum_repositories=0):
        super(PullRequester, self).__init__()

        if os.path.exists( github_token ):
            with open( github_token, 'r', ) as input_file:
                github_token = input_file.read()

        self.init_report()
        self.github_token = github_token.strip()
        self.maximum_repositories = maximum_repositories

    def init_report(self):
        self.repositories_results = {}
        self.skip_reasons = [
            'No commits between',
            'A pull request already exists',
        ]

        for reason in self.skip_reasons:
            self.repositories_results[reason] = []

        self.repositories_results['Unknown Reason'] = []
        self.repositories_results['Successfully Created'] = []

    def parse_gitmodules(self, gitmodules_file):
        log.newline()
        log( 1, 'gitmodules_file', gitmodules_file )

        # using username and password
        # github_api = github.Github("user", "password")

        # or using an access token
        github_api = github.Github( self.github_token )

        # Github Enterprise with custom hostname
        # github_api = github.Github(base_url="https://{hostname}/api/v3", login_or_token="access_token")

        # https://stackoverflow.com/questions/45415684/how-to-stop-tabs-on-python-2-7-rawconfigparser-throwing-parsingerror/
        with open( gitmodules_file ) as fakeFile:
            # https://stackoverflow.com/questions/22316333/how-can-i-resolve-typeerror-with-stringio-in-python-2-7
            fakefile = io.StringIO( fakeFile.read().replace( u"\t", u"" ) )

        general_settings_configs = configparser.RawConfigParser()
        general_settings_configs._read( fakefile, gitmodules_file )

        request_index = 0
        successful_resquests = 0

        sections       = general_settings_configs.sections()
        sections_count = len( sections )

        for section, pi in sequence_timer( sections, info_frequency=0 ):
            request_index += 1
            progress       = progress_info( pi )

            # For quick testing
            if self.maximum_repositories and request_index > self.maximum_repositories:
                break

            log.newline()
            log( 1, "{:s}, {:3d}({:d}) of {:d}... {:s}".format(
                    progress, request_index, successful_resquests, sections_count, section ) )

            downstream = get_section_option( section, "url", general_settings_configs )
            upstream = get_section_option( section, "upstream", general_settings_configs )

            upstream_user, upstream_repository = parse_github( upstream )
            downstream_user, downstream_repository = parse_github( downstream )

            if not upstream_user or not upstream_repository:
                log( 1, "Skipping %s because the upstream is not defined...", section )
                continue

            branches = get_section_option( section, "branches", general_settings_configs )
            local_branch, upstream_branch = parser_branches( branches )

            log( 1, branches )
            log( 1, 'upstream', upstream )
            log( 1, 'downstream', downstream )

            if not local_branch or not upstream_branch:
                log.newline( count=3 )
                log( 1, "ERROR! Invalid branches `%s`", branches )

            if not downstream_user or not downstream_repository:
                log.newline( count=3 )
                log( 1, "ERROR! Invalid downstream `%s`", downstream )

            fork_user = github_api.get_user( downstream_user )
            fork_repo = fork_user.get_repo( downstream_repository )
            full_upstream_name = "{}/{}@{}".format( upstream_user, upstream_repository, upstream_branch )

            try:
                fork_pullrequest = fork_repo.create_pull(
                        "Update from {}".format( full_upstream_name ),
                        wrap_text( r"""
                            The upstream repository `{}` has some new changes that aren't in this fork.
                            So, here they are, ready to be merged!

                            This Pull Request was created programmatically by the
                            [githubpullrequests](https://github.com/evandrocoan/githubpullrequests).
                        """.format( full_upstream_name ), single_lines=True, ),
                        local_branch,
                        '{}:{}'.format( upstream_user, upstream_branch ),
                        False
                    )

                # Then play with your Github objects
                successful_resquests += 1
                log( 1, 'Successfully Created:', fork_pullrequest )

                self.repositories_results['Successfully Created'].append(section)
                fork_pullrequest.add_to_labels( "backstroke" )

            except github.GithubException as error:
                error = str( error )
                log( 1, 'Skipping `%s` due `%s`', section, error )

                for reason in self.skip_reasons:
                    if reason in error:
                        self.repositories_results[reason].append(section)
                        break

                else:
                    self.repositories_results['Unknown Reason'].append(error)

    def publish_report(self):
        log.newline()
        log.clean('Repositories results:')

        for key, values in self.repositories_results.items():
            log.newline()
            log.clean('   ', key)

            if values:
                index = 0

                for item in values:
                    index += 1
                    log.clean('        %s. %s', index, item)

            else:
                log.clean('        No results.')


def parser_branches(branches):
    matches = re.search( r'(.+)\-\>(.+),', branches )

    if matches:
        return matches.group(2), matches.group(1)

    return "", ""


def parse_github(url):
    matches = re.search( r'github\.com\/(.+)\/(.+)', url )

    if matches:
        return matches.group(1), matches.group(2)

    return "", ""


def get_section_option(section, option, configSettings):

    if configSettings.has_option( section, option ):
        return configSettings.get( section, option )

    return ""


if __name__ == "__main__":
    main()
