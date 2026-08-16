# 快速入门

> **关于本译文。** 本文由 AI 从英文翻译而来，**未经中文母语者审校**，措辞上可能存在
> 不准确之处。[英文文档](https://hinatahugu29.github.io/Blender_Seamless_CAD/quickstart/) 为正式版本，若有出入，以英文版为准。
>
> 对应 2026-08-09 版英文文档。
>
> **插件界面为英文。** 本文中的按钮名称保留英文原文，与屏幕上显示的一致，并在必要时
> 补充说明其含义。

本指南带你从安装一路走到导出 STEP 文件，大约需要十分钟。

Seamless CAD 目前为测试版，出售的是 Windows 版。本文内容同样适用于 Linux 与
macOS (Apple Silicon) 的测试版本——插件本身是相同的。

---

## 1. 安装

1. 在 Blender 中打开 `Edit > Preferences > Add-ons > Install...`
2. 选择 `CAD_<版本>_install.zip` 文件
3. 启用该插件
4. 在 3D 视图中按 <kbd>N</kbd> 打开侧边栏，会出现 **Seamless** 选项卡

需要 Blender 4.2 或更高版本。开发与测试均在 5.1 上进行。

## 2. 开始使用

打开 **Seamless** 选项卡。在尚未创建任何内容时，侧边栏只有一个按钮：

- **Start Seamless CAD**

按下它，几何内核会启动，并创建你的第一个 CAD 零件。

> **实际发生了什么：** 形状并非由 Blender 的网格系统计算，而是由独立进程中的
> OpenCASCADE (OCCT) 计算，Blender 只负责绘制结果。这也是插件需要附带一个可执行
> 文件、并且首次启动需要稍等片刻的原因。

## 3. 工作区的概念

**Active CAD Workspace** 面板决定你正在编辑哪个零件。

- 下拉菜单用于选择当前的零件集合
- **Add New CAD Part** 用于新建另一个彼此独立的零件
- 垃圾桶图标删除当前零件

下方各面板的所有操作**只作用于当前选中的零件**。如果下方的面板没有出现，说明尚未
选中有效的零件，请从下拉菜单中选择一个。

## 4. 创建第一个形状

打开 **Create** 面板，按下 **Box**。

视图中出现一个长方体，同时 **Feature Tree** 面板中也会增加一行。这两者是同一个
对象的两种呈现：视图显示计算出的结果，而 Feature Tree 显示生成该结果的操作步骤。

Create 面板按用途分行排列：

| 行 | 内容 |
|---|---|
| 实体 | Box, Cyl, Sph, Cone, Torus |
| 曲线与轮廓 | Curv, Plin, Arc, Surf, Slot, Poly, Gear, Helix, Rev |
| 扫掠形状 | Sweep, Loft |
| 分组 | Group ( , Group ) |
| 草图 | Start Sketch, on Face |

## 5. 事后仍可修改——这才是重点

在 **Feature Tree** 中点击长方体所在的行，下方的 **Active Property Editor** 面板
就会显示它的参数。试着改一下宽度。

形状会重新生成。没有任何东西被破坏，你可以反复修改。

这就是这里所说的「非破坏性」，也是选择本插件而非 Blender 自带建模工具的主要理由。
二十步之前创建的长方体，现在依然是一个可以编辑尺寸的长方体。

你也可以直接移动形状：在视图中选中它的代理对象，像平时使用 Blender 那样按
<kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd>，几何体会实时跟随。

## 6. 挖一个孔

1. 按 **Cyl** 添加一个圆柱
2. 将它摆放到贯穿长方体的位置
3. 在 **Active Property Editor** 中，把该圆柱的布尔运算设为「减去」

Feature Tree 自上而下依次求值，因此这个圆柱会从它上方的所有内容中减去。
**顺序是有意义的**——这是一条构建历史，而不是图层的堆叠。

## 7. 倒圆角

1. 进入选择模式：**Selection Mode > ENTER Selection Mode**
2. 用选择类型按钮指定你要选取的是面还是边
3. 在视图中点击需要的边
4. 打开 **Modify & Pattern**，按下 **Fillet**

> **提示：** 在选择模式下按住 <kbd>Alt</kbd>，可以不退出该模式直接使用 Blender
> 的常规操作控制器。

**Chamf**（倒角）的操作方式相同，只是以平切代替圆角。

## 8. 调整质量与速度

**Quality & Export** 面板控制内核的计算结果转换为显示网格时的精细程度。

- **Linear** 与 **Curvature**——显示用的细分精度。数值越小越精细，也越慢。
- **Fast Modifier Preview** 与 **Live Boolean Preview**——以精确度换取拖动时的
  流畅度。如果预览看起来不正确，请关闭它们；**最终结果始终会被精确计算。**
- **Use High Quality Bake**——仅在烘焙时生效的另一套更精细的设置。你可以在较粗糙
  的显示精度下工作，而不影响输出质量。

## 9. 回溯构建历史

Feature Tree 每一行的右端都有一个图钉图标。将某一行固定后，零件只会计算到该处为止，
其后的所有内容都会变灰并被忽略。

这可以用来查看中间状态，或者在已有的历史中间插入新的操作。取消固定即可恢复整棵树的
计算。

## 10. 输出结果

有两种方式，用途各不相同。

**Bake to Mesh**（`Quality & Export > Bake to Mesh`）会把零件转换为普通的 Blender
网格。渲染、雕刻，以及其他需要 Blender 几何体的场合请用这个。若结果用于渲染，
请先启用 **Use High Quality Bake**。

**Export STEP**（`Quality & Export > Export > STEP`）会写出可供其他 CAD 软件使用的
真正的 B-Rep STEP 文件（AP214 IS）。保存的是精确曲面，而非三角面近似。

> **比例：** 导出时，**1 个 Blender 单位写为 1 毫米**。一个 10 单位的长方体，在
> FreeCAD 或 Fusion 中会是 10 毫米的长方体。设定尺寸时请以此为前提。
>
> STEP 导出会携带零件名称和装配结构（零件名称取自 Part 的集合名称）。
> **仅颜色不会被导出** —— 插件中没有可以设定颜色的位置，因此文件中没有颜色可写。

## 接下来可以了解

- **Import STEP** / **Import SVG**——把外部几何体导入到构建历史中
- **Start Sketch**——在平面或已有的面上绘制带约束的二维轮廓
- **Modify & Pattern**——Mirror（镜像）、Array（线性阵列）、Circ（环形阵列）、
  Link（关联副本）
- **Cleanup (Unify)**——合并共面的面。**这是刻意设计为手动操作的**，不会自动应用：
  合并面会破坏面的标识信息，而圆角和偏移正是依赖这些标识来定位的。

## 遇到问题时

**Seamless 选项卡中，工作区面板下面什么都没有。**
尚未选中有效的零件集合。请从 **Active CAD Workspace** 的下拉菜单中选择，或按下
**Add New CAD Part**。

**Hide Occluded Edges 是灰色的，无法点击。**
这是有意为之。只有在 WGPU 叠加层关闭**且**完全不透明时，面才会写入深度值；在其他
条件下该设置不会产生任何效果。为了避免出现「能点击却毫无反应」的控件，这里直接将
它禁用。

**拖动时形状看起来不对，松手后又正常了。**
这是快速预览造成的。关闭 **Fast Modifier Preview** 和 **Live Boolean Preview**
即可始终看到精确结果。

**修改后没有任何更新。**
点击 **Modify & Pattern > Topology** 中的刷新图标，可强制重新计算。
