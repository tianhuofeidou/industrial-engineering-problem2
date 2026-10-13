"""兼容原初版测试命令：python -m problem2.tests。"""
import runpy

if __name__ == '__main__':
    runpy.run_module('problem2.tests.test_legacy', run_name='__main__', alter_sys=True)
