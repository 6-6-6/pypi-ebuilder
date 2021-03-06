# OSPP 2020 项目申请书

项目名称：Gentoo PyPI ebuild 生成器

Gentoo PyPI 现状：
1. 有大量的包依赖 PyPI 上的包，这些包大多都是比较标准的基于 setuptools 的安装方法
2. 目前 Gentoo 的 Python 包都是维护者手动维护的，工作量很大，并且总是要编写很相似的 ebuild，大部分都是重复的工作
3. 以往有 gs-pypi 的实现，但作者在几年前不再更新，也没有动态

项目的意义：
1. 减少重复工作，简化维护者的工作
2. 让更多的 PyPI 上的包纳入 gentoo 的环境里，减少 portage 和 pip 的冲突

项目详细方案：

1. 实现 PyPI 所有 Python 包的元数据的抓取和解析
2. 基于 python eclass 实现一个用于 pypi 的 eclass
3. 按照 PyPI 上的元数据，指定一个包，生成它和它的所有依赖的对应的 ebuild
4. 通过 CI 进行测试，测试安装指定的一些 package 并进行测试

项目开发时间计划：

1. 7.1-7.15 两星期：了解 gs-pypi 工作原理，尝试手动编写一个类似的 ebuild 并进行测试
2. 7.16-7.31 两星期：使用 Python 编写简单的 ebuild 生成器，并把通用的部分写到单独的 eclass 中
3. 8.1-8.15 两星期：优化 ebuild 生成器，支持更复杂的依赖关系，并可以生成包和包的依赖的所有 ebuild
4. 8.16-8.31 两星期：支持多 Python 版本共存，实现 CI 自动测试
5. 9.1-9.15 两星期：编写文档，设计非标准 pypi 包的 ebuild 方案
6. 9.16-9.30 两星期：和认识的 Gentoo 用户进行实际测试，按照反馈进行改善
