# Copyright: 2016 Tim Harder <radhermit@gmail.com>
# License: BSD/GPL2

from pkgcore.scripts import pclean
from pkgcore.test.scripts.helpers import ArgParseMixin
from snakeoil.test import TestCase


class CommandlineTest(TestCase, ArgParseMixin):

    _argparser = pclean.argparser

    suppress_domain = True

    def test_parser(self):
        self.assertError('the following arguments are required: subcommand')
