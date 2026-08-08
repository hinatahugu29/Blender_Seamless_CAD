# Seamless CAD

在 Blender 内部进行非破坏性 CAD 建模的插件。

形状由 **OpenCASCADE (OCCT)** 计算，而非 Blender 的网格系统，计算结果绘制在视图中。
基本体、布尔运算、圆角与倒角都以 **Feature Tree**（构建历史）的形式保留，随时可以
回头修改参数。用 <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> 移动视图中的代理对象，
几何体会实时跟随。

输出有两种方式：在 Blender 内部使用则选 **Bake to Mesh**，交给其他 CAD 软件则选
**Export STEP**（真正的 B-Rep 文件）。

> **测试版。** 仅支持 Windows。macOS 与 Linux 的适配正在进行中，目前还没有可供
> 下载的版本。

## 文档

- **[快速入门](quickstart.md)**——从安装到导出 STEP，约十分钟

中文翻译有意仅限于这一页。其余文档请参阅[英文版](https://hinatahugu29.github.io/Blender_Seamless_CAD/)。

## 关于语言

**插件界面为英文**，因此术语以[英文文档](https://hinatahugu29.github.io/Blender_Seamless_CAD/)为准——只有英文版能保证与
按钮上的文字完全一致。

中文译文由 AI 完成，未经母语者审校。若与英文版有出入，以英文版为准。
