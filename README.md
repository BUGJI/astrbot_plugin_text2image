# 📷 文字转图片插件

该插件支持将文本转换为图片，可按照高度自定义的规则生成图片文件。

这个插件使用非常简单，不需要专业知识，只需要会复制粘贴即可

## 💡 使用方法
基础命令格式：
```bash
texttool generate 请输入文本
```
- 按插件默认配置（字体、样式）生成图片
- 默认生成**透明底黑字**图片，高度固定，宽度随文字数量自适应

## 📖 新手教程
> ⚠️ 新用户建议先阅读本章节，帮助理解核心功能

### 参数使用规则
在生成命令中，可在 `generate` 后、待生成文本前添加自定义参数，示例：
```bash
texttool generate mode:char 请输入文本
```

#### 多图模式的文件输出规则
当使用非 `single`（单图）模式时，任务会加入排程，完成后发送压缩包，文件命名规则为：
```
[时间戳]_texttool_[8位顺序数字].png
```
示例：
```
12345678_texttool_00000000.png
12345678_texttool_00000001.png
12345678_texttool_00000002.png
```
✅ Windows 文件资源管理器可按文件名正常排序

### 核心参数：生成模式（mode）
mode 参数支持 5 种生成模式，参数格式为 `mode:值`：

| 参数值 | 说明 |
|--------|------|
| single | 单图模式（默认）|
| char   | 按字符分隔，一个字符一张图 |
| word   | 按词语分隔（空格分隔），一个词语一张图 |
| line   | 按行分隔，一行一张图 |
| token  | 按 `\|` 分隔（精确分隔），需提前处理文本 |

示例：
```bash
texttool generate mode:word hello world
```

### 字体选择
可指定程序支持的字体，参数格式为 `font:字体名`：

1. 查看可用字体列表：
   ```bash
   texttool font_list
   ```
2. 使用指定字体生成图片（需管理员提前配置字体文件）：
   ```bash
   texttool generate mode:word font:Arial hello world
   ```
   > 字体文件需放置在 `plugin_data/astrbot_plugin_text2image/ttf` 目录，字体别名在上级目录的 `fonts.json` 中定义

## 🚀 进阶教程
按「常用度」分为三类参数，可组合使用。

### 1. 常用参数
#### 生成模式（重复说明，可根据需求保留/删除）
同「新手教程 - 核心参数：生成模式」

#### 背景颜色（bg_color）
- 参数格式：`bg_color:值`
- 支持 16 进制 RGB(A) 值，示例：`bg_color:#00FF00`
- 不写 Alpha 值则默认不透明

#### 字体颜色（text_color）
- 参数格式：`text_color:值`
- 支持 16 进制 RGB(A) 值，示例：`text_color:#00FF00`
- 不写 Alpha 值则默认不透明

#### 中心模式（center_mode）
适用于特殊字符（如「氵」）的居中显示：
- 参数格式：`center_mode:值`
- 可选值：`geometry`（按文字实际大小计算）、`visual`（默认）
- 示例：`center_mode:geometry`

#### 清晰度（dpi）
- 参数格式：`dpi:值`
- 默认值：72
- 推荐清晰值：200-800
- 示例：`dpi:300`

### 2. 进阶参数
#### 边缘留白（padding）
- 参数格式：`padding:值`
- 作用：为图片四周边缘增加留白（单位：像素）
- 示例：`padding:10`

#### 中心点偏移（x/y 轴）
调整文字在图片中的中心点位置：
- X 轴偏移：`x_offset_ratio:值`
- Y 轴偏移：`y_offset_ratio:值`
- 默认值：0.5（居中），取值范围 0-1
- 示例：`x_offset_ratio:0.3`（向左偏移）

### 3. 高级参数
（以下参数有默认最优值，非特殊需求无需修改）

#### 文字大小（font_size）
- 参数格式：`font_size:值`
- 示例：`font_size:24`

#### 图片高度（canvas_height）
- 参数格式：`canvas_height:值`
- 示例：`canvas_height:100`

#### 图片宽度（canvas_width）
- 参数格式：`canvas_width:值`
- ⚠️ 注意：设置后宽度固定，可能导致文字大小不一致或超出边界

## 🙏 致谢
- ChatGPT：协助编写核心代码
- 豆包：帮我优化这个排版没救的文档