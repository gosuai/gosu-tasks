from setuptools import setup

setup(
    name='gosu-tasks',
    version='0.0.0',
    classifiers=[],
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    install_requires=['pygithub', 'gitpython'],
    py_modules=['gosu_tasks'],
)
