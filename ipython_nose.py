import cgi
import os
import traceback
import sys
import types
import unittest
import uuid

from nose import core as nose_core
from nose import loader as nose_loader
from nose.config import Config, all_config_files
from nose.plugins.base import Plugin
from nose.plugins.manager import DefaultPluginManager
from IPython.core import displaypub, magic
from IPython.zmq.displayhook import ZMQShellDisplayHook


class DummyUnittestStream:
    def write(self, *arg):
        pass
    def writeln(self, *arg):
        pass
    def flush(self, *arg):
        pass


class NotebookLiveOutput(object):
    def __init__(self):
        self.output_id = 'ipython_nose_%s' % uuid.uuid4().hex
        displaypub.publish_html(
            '<div id="%s"></div>' % self.output_id)
        displaypub.publish_javascript(
            'document.%s = $("#%s");' % (self.output_id, self.output_id))

    def finalize(self):
        displaypub.publish_javascript('delete document.%s;' % self.output_id)

    def publish_chars(self, chars):
        displaypub.publish_javascript(
            'document.%s.append($("<span>%s</span>"));' % (
                self.output_id, cgi.escape(chars)))


class ConsoleLiveOutput(object):
    def __init__(self, stream_obj):
        self.stream_obj = stream_obj

    def finalize(self):
        self.stream_obj.stream.write('\n')

    def publish_chars(self, chars):
        self.stream_obj.stream.write(chars)


class IPythonDisplay(Plugin):
    """Do something nice in IPython."""

    name = 'ipython-html'
    enabled = True
    score = 2

    _nose_css = '''\
    <style type="text/css">
        span.nosefailedfunc {
            font-family: monospace;
            font-weight: bold;
        }
        div.noseresults {
            width: 100%;
        }
        div.nosefailbar {
            background: red;
            float: left;
            padding: 1ex 0px 1ex 0px;
        }
        div.nosepassbar {
            background: green;
            float: left;
            padding: 1ex 0px 1ex 0px;
        }
        div.nosefailbanner {
            width: 75%;
            background: red;
            padding: 0.5ex 0em 0.5ex 1em;
            margin-top: 1ex;
            margin-bottom: 0px;
        }
        pre.nosetraceback {
            background: pink;
            padding-left: 1em;
            margin-left: 0px;
            margin-top: 0px;
            display: none;
        }
    </style>
    '''

    _show_hide_js = '''
    <script>
        setTimeout(function () {
            $('.nosefailtoggle').bind(
                'click',
                function () {
                    $(
                        $(this)
                            .parent()
                            .parent()
                            .children()
                            .filter('.nosetraceback')
                    ).toggle();
                }
            );},
            0);
    </script>
    '''

    _summary_template_html = '''
    <div class="noseresults">
      <div class="nosefailbar" style="width: {failpercent}%">&nbsp;</div>
      <div class="nosepassbar" style="width: {passpercent}%">&nbsp;</div>
      {text}
    </div>
    '''

    _summary_template_text = '''{text}'''

    def _summary(self, numtests, numfailed, template):
        if numfailed > 0:
            text = "%d/%d tests passed; %d failed" % (
                numtests - numfailed, numtests, numfailed)
        else:
            text = "%d/%d tests passed" % (numtests, numtests)

        failpercent = int(float(numfailed) / numtests * 100)
        if numfailed > 0 and failpercent < 5:
            # ensure the red bar is visible
            failpercent = 5
        passpercent = 100 - failpercent

        return template.format(**locals())

    _tracebacks_template = '''
    <div class="nosefailure">
        <div class="nosefailbanner">
          failed: <span class="nosefailedfunc">{name}</span>
            [<a class="nosefailtoggle" href="#">toggle traceback</a>]
        </div>
        <pre class="nosetraceback">{formatted_traceback}</pre>
    </div>
    '''

    def _tracebacks(self, failures):
        output = []
        for test, exc in failures:
            name = cgi.escape(test.shortDescription() or str(test))
            formatted_traceback = cgi.escape(
                ''.join(traceback.format_exception(*exc)))
            output.append(self._tracebacks_template.format(**locals()))
        return ''.join(output)


    def __init__(self):
        super(IPythonDisplay, self).__init__()
        self.html = []
        self.num_tests = 0
        self.failures = []

    def addSuccess(self, test):
        self.live_output.publish_chars('.')

    def addError(self, test, err):
        self.live_output.publish_chars('E')
        self.failures.append((test, err))

    def addFailure(self, test, err):
        self.live_output.publish_chars('F')
        self.failures.append((test, err))

    def addSkip(self, test):
        self.live_output.publish_chars('S')

    def begin(self):
        # This feels really hacky
        if isinstance(sys.displayhook, ZMQShellDisplayHook):
            self.live_output = NotebookLiveOutput()
        else:
            self.live_output = ConsoleLiveOutput(self)

    def finalize(self, result):
        self.result = result
        self.live_output.finalize()

    def setOutputStream(self, stream):
        # grab for own use
        self.stream = stream
        return DummyUnittestStream()

    def startContext(self, ctx):
        pass

    def stopContext(self, ctx):
        pass

    def startTest(self, test):
        self.num_tests += 1

    def stopTest(self, test):
        pass

    def _repr_html_(self):
        if self.num_tests <= 0:
            return 'No tests found.'

        output = [self._nose_css, self._show_hide_js]

        output.append(self._summary(
            self.num_tests, len(self.failures), self._summary_template_html))
        output.append(self._tracebacks(self.failures))
        return ''.join(output)

    def _repr_pretty_(self, p, cycle):
        if self.num_tests <= 0:
            p.text('No tests found.')
            return
        p.text(self._summary(
            self.num_tests, len(self.failures), self._summary_template_text))

def get_ipython_user_ns_as_a_module():
    test_module = types.ModuleType('test_module')
    test_module.__dict__.update(get_ipython().user_ns)
    return test_module

def makeNoseConfig(env):
    """Load a Config, pre-filled with user config files if any are
    found.
    """
    cfg_files = all_config_files()
    manager = DefaultPluginManager()
    return Config(env=env, files=cfg_files, plugins=manager)

def nose(line, test_module=get_ipython_user_ns_as_a_module):
    if callable(test_module):
        test_module = test_module()
    config = makeNoseConfig(os.environ)
    loader = nose_loader.TestLoader(config=config)
    tests = loader.loadTestsFromModule(test_module)
    plug = IPythonDisplay()

    nose_core.TestProgram(
        argv=['ipython-nose', '--with-ipython-html'], suite=tests,
        addplugins=[plug], exit=False, config=config)

    return plug

def load_ipython_extension(ipython):
    magic.register_line_magic(nose)
