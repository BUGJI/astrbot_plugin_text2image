# astrbot_plugin_text2image

将文本渲染为图片的 AstrBot 插件，使用 Playwright Chromium 渲染。

## 安装

```bash
pip install playwright
playwright install chromium
```

将插件文件夹放入 AstrBot 的插件目录即可。

## 目录结构

```
astrbot_plugin_text2image/
├── main.py              # 主逻辑
├── text_renderer.py     # 文本渲染器
├── fonts/               # 字体文件目录 (放置 .ttf/.otf/.ttc)
└── test_renderer.py     # 测试文件
```

**重要**：将字体文件（.ttf/.otf/.ttc）放入 `fonts/` 目录。

## 使用方法

### 基本命令

| 命令 | 说明 |
|------|------|
| `texttool help` | 显示帮助信息 |
| `texttool pm` | 参数说明 |
| `texttool list` | 分页查看可用字体列表 |
| `texttool listall` | 查看所有可用字体（图片形式） |
| `texttool generate <参数> <文本>` | 生成图片 |

### 生成图片

```
texttool generate <文本>
```

示例：
```
texttool generate 你好世界
```

### 参数说明

参数格式：`参数名:值`，多个参数用空格分隔

| 参数 | 说明 | 示例 |
|------|------|------|
| `font` | 字体名称，使用 `texttool list` 查看可用字体 | `font:宋体` |
| `mode` | 渲染模式 | 见下方 |
| `css` | 自定义 CSS 样式 | `css:color:red;font-size:80px` |

#### 渲染模式 (mode)

- `single`（默认）：整行渲染
- `char`：按单个字符渲染
- `word`：按单词渲染（空格分隔）
- `line`：按行渲染
- `token`：按 `|` 分隔渲染
- `article`：文章模式，保留完整空格和换行，支持 CSS 定义宽度自动换行

### CSS 自定义

可以使用 `css:` 参数自定义样式：

```
texttool generate css:"color:#FF0000;font-size:100px;font-weight:bold" 你好

# 同样，css代码支持换行和空格，让其看起来更可读
texttool generate css:"
color:#FF0000;
font-size:100px;
font-weight:bold
" 你好
```

支持任意可被Chromium解析的CSS属性，直接作用

### 示例

```
# 简单使用
texttool generate Hello World

# 指定字体
texttool generate font:黑体 你好

# 红色大字
texttool generate css:"color:red;font-size:120px" 警告

# 多行渲染
texttool generate mode:line 第一行
第二行
第三行

# 混色字
texttool generate css:"
background-clip:text;
color:transparent;
background:linear-gradient(45deg,#f09,#00f);
-webkit-background-clip:text;" AI超级配色大字

# 文章模式（保留空格换行，支持CSS定义宽度自动换行）
texttool generate mode:article css:"width:500px;font-size:40px" 标题

第一段内容，会根据宽度自动换行。

第二段内容。

```

### 查看字体列表

```
# 文字列表（分页）
texttool list 可以加页码

# 图片形式查看所有字体
texttool listall
```

## 配置

在 AstrBot 管理界面配置：

- **默认字体**：不填时使用的字体
- **单次最大字符数**：防止生成过多
- **单次最大图片数**：防止刷屏
- **黑名单**：禁用的群号

## 字体说明

- 自定义字体文件
  只需将字体文件放入 `fonts/` 目录即可自动识别。
- 字体选择
  不一定要在font参数后面填字体名字，编号也可以：font:123

支持的格式：
- `.ttf` - TrueType Font
- `.otf` - OpenType Font
- `.ttc` - TrueType Collection

## 依赖

- playwright
- Pillow

## 鸣谢

- 基于 Playwright Chromium 渲染
- MiniMax-M2.5