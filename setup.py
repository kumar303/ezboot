import os

from setuptools import setup, find_packages


def local_file(fn):
    return open(os.path.join(os.path.dirname(__file__), fn))


setup(name='ezboot',
      version='1.1.8',
      description="Automatically configure a Boot2Gecko Device. It's so ez!",
      long_description=local_file('README.rst').read(),
      author='Kumar McMillan',
      author_email='kumar.mcmillan@gmail.com',
      license='Apache 2',
      url='https://github.com/kumar303/ezboot',
      include_package_data=True,
      classifiers=[],
      entry_points="""
          [console_scripts]
          ezboot = ezboot:main
          """,
      packages=find_packages(exclude=['tests']),
      install_requires=[ln.strip() for ln in
                        local_file('requirements.txt')
                        if not ln.startswith('#')])
