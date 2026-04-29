import asyncio
import time
import zipfile
import shutil
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import File as CompFile
from astrbot.api.message_components import Image as CompImage
from astrbot.api import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.api.star import StarTools


from .text_renderer import render_text_sync, render_batch_concurrent


async def _render_batch_async(
    tokens: List[str],
    folder: Path,
    font_path: Path,
    params: Dict[str, Any],
    max_concurrent: int = 8,
) -> List[Path]:
    """异步并发渲染批次图片"""
    return await render_batch_concurrent(
        tokens=tokens,
        folder=folder,
        font_path=font_path,
        params=params,
        max_concurrent=max_concurrent,
    )


@register("texttool", "BUGJI", "文本转图片", "0.3.0", "https://github.com/BUGJI/astrbot_plugin_text2image")
class TextTool(Star):

    ALLOWED_PARAMS = {
        "font",
        "mode",
        "css",
        "ext",
    }

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        self.config = config
        self.name = "astrbot_plugin_text2image"

        self.plugin_root = Path(__file__).parent
        self.fonts_dir = self.plugin_root / "fonts"

        # 兼容性兜底
        if self.config.compatibility.get("startool_path", False):
            self.data_path = StarTools.get_data_dir(self)
        else:
            self.data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        self.cache_path = self.data_path / "cache"
        
        # 菜单图片发送模式（拆分为 list 和 listall）
        self.list_menu_image_send_mode = self.config.compatibility.get("list_menu_image_send_mode", "text")
        self.listall_menu_image_send_mode = self.config.compatibility.get("listall_menu_image_send_mode", "image")
        
        self.single_image_send_by_file = self.config.compatibility.get("single_image_send_by_file", True)
        
        self.blacklist = self.config.compatibility.get("blacklist", [])
        self.blacklist = {str(gid) for gid in self.blacklist}
        self.blacklist_notice = self.config.compatibility.get("blacklist_notice", "当前群暂不支持此功能。")
        self.allow_get_font = self.config.compatibility.get("allow_get_font", False)
        
        self.max_task = int(self.config.limit.get("max_task", 4))
        if self.max_task <= 0:
            logger.warning("max_task <= 0，自动修正为 1")
            self.max_task = 1
            
        self.max_chars_per_task = int(self.config.limit.get("max_chars_per_task", 20000))
        self.max_images_per_task = int(self.config.limit.get("max_images_per_task", 1000))
        self.max_concurrent_renders = int(self.config.limit.get("max_concurrent_renders", 8))
        if self.max_concurrent_renders <= 0:
            logger.warning("max_concurrent_renders <= 0，自动修正为 1")
            self.max_concurrent_renders = 1
        self.max_concurrent_font_samples = int(self.config.limit.get("max_concurrent_font_samples", 8))
        if self.max_concurrent_font_samples <= 0:
            logger.warning("max_concurrent_font_samples <= 0，自动修正为 1")
            self.max_concurrent_font_samples = 1
        self.fonts_per_page = int(self.config.limit.get("fonts_per_page", 20))
        self.font_list_columns = int(self.config.limit.get("font_list_columns", 3))
        # 校验 font_list_columns 范围
        if self.font_list_columns < 1:
            logger.warning(f"font_list_columns < 1，自动修正为 1")
            self.font_list_columns = 1
        elif self.font_list_columns > self.fonts_per_page:
            logger.warning(f"font_list_columns > fonts_per_page，自动修正为 {self.fonts_per_page}")
            self.font_list_columns = self.fonts_per_page
        self.default_font = self.config.get("default_font", "宋体2")
        
        # self.queue = asyncio.Queue(maxsize=self.max_task)
        # logger.info(f"启动  个 worker，队列上限 {self.max_task}")

    async def initialize(self):
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.fonts_dir.mkdir(exist_ok=True)

        logger.info("Text2Image 插件已初始化")

    # =======================
    # 指令系统
    # =======================

    @filter.command_group("texttool")
    def texttool(self):
        pass

    @filter.llm_tool(name="textgen")
    async def textgen(
        self,
        event: AstrMessageEvent,
        content: str,
        font: str = "",
        mode: str = "article",
        css: str = ""
    ):
        '''文本转图片生成器。根据参数生成文本图片。

        参数选择规则：
        - mode:char - 当用户说"每个字独立"、"逐字"时
        - mode:article - 当内容有多段落、需要自动换行时（推荐默认）除非用户主动要求"一个一个发"，否则不要多次调用此
        - mode:single - 简短单行内容，除非用户主动要求"一个一个发"，否则不要多次调用此
        - mode:line - 每行分别渲染，填写参数时建议使用\\n分割，以便程序处理
        - mode:word - 按单词渲染，填写参数时建议使用空格分割，以便程序处理
        - mode:token - 按|分隔渲染

        Args:
            content(string): 要渲染的文本内容，必须
            font(string): 字体名称或编号(可选，如"宋体"或"1")
            mode(string): 渲染模式，默认为article
            css(string): CSS样式(可选，如"color:red;font-size:100px")
        '''
        params = {}
        
        # 处理参数
        if font:
            params["font"] = font
        if mode:
            params["mode"] = mode
        if css:
            params["css"] = css
        
        # 显示使用的参数
        param_info = []
        if font:
            param_info.append(f"font:{font}")
        param_info.append(f"mode:{mode}")
        if css:
            param_info.append(f"css:{css}")
        
        yield event.plain_result(f"使用参数: {' '.join(param_info)}")
        
        # 创建后台任务执行生成（避免超时）
        async def background_generate(params, tokens):
            try:
                await self._process_and_send(event, params, tokens)
            except Exception as e:
                logger.exception(f"后台生成图片失败: {e}")
                await event.plain_result(f"生成失败: {e}")
        
        # 按 mode 分割内容
        tokens = self._split_content(content, mode)
        
        # 计算预计时间：按照一个线程 6 秒计算，同时考虑并发线程数
        # 如配置的线程为 4，需要执行 6 个任务，则时间为 ceil(6/4)*6 = 2*6 = 12 秒
        import math
        batches = math.ceil(len(tokens) / self.max_concurrent_renders)
        estimated_seconds = batches * 6
        
        if estimated_seconds >= 60:
            minutes = estimated_seconds // 60
            seconds = estimated_seconds % 60
            if seconds > 0:
                time_text = f"{minutes} 分钟 {seconds} 秒"
            else:
                time_text = f"{minutes} 分钟"
        else:
            time_text = f"{estimated_seconds} 秒"
        
        # 立即创建后台任务
        asyncio.create_task(background_generate(params.copy(), tokens))
        
        yield event.plain_result(f"任务已下发，图片生成中... 预计 {time_text}" + 
                                 f" (已使用{self.max_concurrent_renders}线程渲染)" if self.max_concurrent_renders > 1 else "")

    @texttool.command("help")
    async def help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        yield event.plain_result("texttool 帮助信息:\n"
                                "texttool generate [参数:值] 文本内容 - 生成文本图片\n"
                                "texttool pm - 基本参数帮助\n"
                                "texttool listall - 查看所有可用字体\n"
                                "texttool list [页码] - 分页查看可用字体列表\n"
                                "texttool get [字体 ID] - 获取字体源文件（需要管理员开启允许）\n"
                                "texttool task - 查看当前任务队列状态")

    @texttool.command("pm")
    async def param_help(self, event: AstrMessageEvent):
        """基本参数帮助"""
        msg_lines = [
            "文本转图片工具参数说明:",
            "",
            "在待输入前部分添加参数，格式为 参数名:值，多个参数用空格分隔",
            " 例子：",
            " texttool generate font:宋体 你好世界",
            " texttool generate css:color:red;font-size:100px 你好世界",
            "",
            "font - 字体名称，请使用 texttool list 查看可用字体",
            "mode - single（默认）整行渲染，char按字渲染，word分词渲染，line分行渲染，token分块渲染",
            "css - 自定义 CSS 样式，如 css:color:red;font-size:80px",
        ]
        yield event.plain_result("\n".join(msg_lines))
    
    @texttool.command("listall")
    async def listall(self, event: AstrMessageEvent):
        """列出所有可用字体（图片形式）"""
        fonts = self._scan_fonts()
        if not fonts:
            yield event.plain_result("未找到任何字体文件，请在插件目录的 fonts 文件夹中添加字体文件")
            return
        
        # 字体示例图缓存目录
        font_samples_dir = self.data_path / "font_samples"
        font_samples_dir.mkdir(parents=True, exist_ok=True)
        
        # 检测缓存是否为空
        cached_count = len(list(font_samples_dir.glob("*.png")))
        if cached_count == 0:
            yield event.plain_result("⚠️ 第一次使用需要缓存大量图片，可能需要较长时间，请耐心等待...")
        
        sample_text = "你好 123Abc"
        font_rows = []
        missing_count = 0

        # 预先渲染每个字体的示例图（带缓存），并按 fonts_per_page 插入分页标记
        sorted_fonts = sorted(fonts.items(), key=lambda x: x[0])
        total_fonts = len(sorted_fonts)
        fonts_per_page = self.fonts_per_page

        # 收集需要渲染的字体任务
        render_tasks = []
        for idx, (font_name, font_path) in enumerate(sorted_fonts):
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            if not font_img_path.exists():
                render_tasks.append((idx, font_name, font_path, font_img_path))

        # 并发渲染缺失的字体示例图
        if render_tasks:
            logger.debug(f"[DEBUG] 需要渲染 {len(render_tasks)} 个字体示例图")
            yield event.plain_result(f"正在生成 {len(render_tasks)} 个字体示例图...")

            semaphore = asyncio.Semaphore(self.max_concurrent_font_samples)

            async def render_font_sample(task_idx, task_font_name, task_font_path, task_font_img_path):
                async with semaphore:
                    try:
                        logger.debug(f"[DEBUG] 渲染字体示例：{task_font_name}")
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: render_text_sync(
                                text=sample_text,
                                font_path=str(task_font_path),
                                output_path=str(task_font_img_path)
                            )
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"[WARN] 渲染字体 {task_font_name} 失败：{e}")
                        return False

            # 并发执行所有渲染任务
            results = await asyncio.gather(*[
                render_font_sample(tidx, tname, tpath, timgpath)
                for tidx, tname, tpath, timgpath in render_tasks
            ])
            missing_count = sum(results)

        # 构建 HTML 行（网格布局）
        columns = self.font_list_columns
        for idx, (font_name, font_path) in enumerate(sorted_fonts):
            font_img_path = font_samples_dir / f"{font_path.stem}.png"

            if not font_img_path.exists():
                continue

            is_default = " (默认)" if font_name == self.default_font else ""

            # 使用相对路径：cache_path → font_samples 是兄弟目录
            rel_path = f"../font_samples/{font_img_path.name}"

            # 在每页第一个字体前插入分页标记（包括第一页）
            if idx % fonts_per_page == 0:
                page_num = idx // fonts_per_page + 1
                font_rows.append(f'''<tr>
                    <td colspan="{columns}" class="page-break">页 {page_num}</td>
                </tr>''')
                font_rows.append(f'''<tr>
                    <td colspan="{columns}" class="page-tip" style="text-align:left">使用 texttool list <页码> 复制字体昵称</td>
                </tr>''')

            # 每行开始新行
            if idx % columns == 0:
                font_rows.append('<tr>')
            
            # 添加单个字体单元格
            font_rows.append(f"""<td class=\"font-cell\">
                <div style="display:flex; flex-direction: row;">
                    <div class=\"font-index\">{idx + 1}</div>
                    <div class=\"font-name\">{font_name}{is_default}</div>
                </div>
                <div class=\"font-sample\"><img src=\"{rel_path}\" height=\"60\"></div>
            </td>""")
            
            # 每行结束或最后一个字体时闭合行
            if (idx + 1) % columns == 0 or idx == len(sorted_fonts) - 1:
                font_rows.append('</tr>')
        
        # 页尾提示
        font_rows.append(f'''<tr>
            <td colspan="{columns}" class="page-break">底部</td>
        </tr>''')
        font_rows.append(f'''<tr>
            <td colspan="{columns}" class="page-tip" style="text-align:right">使用 texttool list <页码> 复制字体</td>
        </tr>''')

        if missing_count > 0:
            yield event.plain_result(f"正在生成 {missing_count} 个字体示例图...")

        # 计算缓存指纹（基于字体文件修改时间 + fonts_per_page + default_font）
        cache_key_parts = [str(self.fonts_per_page), self.default_font]
        for font_name, font_path in sorted_fonts:
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            # 用字体文件修改时间和示例图修改时间
            font_mtime = font_path.stat().st_mtime
            sample_mtime = font_img_path.stat().st_mtime if font_img_path.exists() else 0
            cache_key_parts.append(f"{font_name}:{font_mtime}:{sample_mtime}")
        
        cache_key = hashlib.md5("".join(cache_key_parts).encode()).hexdigest()
        cached_img_path = self.cache_path / f"fontlist_cached_{cache_key}.png"

        # 检查缓存是否有效
        if cached_img_path.exists():
            logger.debug(f"[DEBUG] 使用缓存的字体列表图片: {cached_img_path} 发送模式: {self.listall_menu_image_send_mode}")
            if self.listall_menu_image_send_mode == "image":
                yield event.image_result(str(cached_img_path))
            elif self.listall_menu_image_send_mode == "file":
                # yield event.plain_result("正在发送字体列表图片（文件方式）...")
                await event.send(event.chain_result([CompFile(file=str(cached_img_path), name="font_list.png")]))
            elif self.listall_menu_image_send_mode == "zipfile":
                # yield event.plain_result("正在发送字体列表图片（压缩包方式）...")
                zip_path = self.cache_path / f"font_lists.zip"
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    zf.write(cached_img_path, arcname="font_list.png")
                # yield event.chain_result(CompFile(file=str(zip_path), name=""))
                await event.send(event.chain_result([CompFile(file=str(zip_path), name="font_list.zip")]))
            
            return
        
        # 构建 HTML（使用相对路径引用缓存图片）
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ background: #FFFFFF; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td {{ background: #FFFFFF; }}
        .font-cell {{
            text-align: center;
            vertical-align: top;
            padding: 8px;
            border-right: 1px solid #ddd;
            border-bottom: 1px solid #ddd;
            width: {100 // columns}%;
        }}
        .font-index {{
            font-family: sans-serif;
            font-size: 16px;
            padding: 4px;
            text-align: center;
            color: #888;
        }}
        .font-name {{
            font-family: sans-serif;
            font-size: 14px;
            color: #bbb;
            padding: 4px;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .font-sample {{
            padding: 8px;
            text-align: center;
            vertical-align: middle;
        }}
        .font-sample img {{
            display: inline-block;
            max-width: 100%;
            height: auto;
        }}
        .page-break {{
            font-family: sans-serif;
            font-size: 20px;
            text-align: left;
            padding: 12px;
            font-weight: bold;
            color: #0066cc;
        }}
        .page-tip {{
            font-family: sans-serif;
            font-size: 14px;
            text-align: center;
            padding: 15px;
            color: #666;
        }}
        h1 {{
            font-family: sans-serif;
            font-size: 32px;
            margin-bottom: 20px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <h1>可用字体列表 ({total_fonts} 种)</h1>
    <table>
        {"".join(font_rows)}
    </table>
</body>
</html>"""
        # 生成最终图片
        uid = hashlib.sha256(str(event.get_sender_id()).encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        img_path = self.cache_path / f"fontlist_{uid}_{ts}.png"
        
        from playwright.async_api import async_playwright
        
        async def render():
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page(viewport={"width": 1200, "height": 800})
                # 先把 HTML 保存为文件，用相对路径引用图片
                html_path = self.cache_path / f"fontlist_{uid}_{ts}.html"
                html_path.write_text(html_content, encoding="utf-8")
                await page.goto(f"file://{html_path.absolute()}")
                await page.wait_for_timeout(1000)
                await page.screenshot(path=str(img_path), full_page=True, omit_background=False)
                await browser.close()
                # 清理 HTML 文件
                if html_path.exists():
                    html_path.unlink(missing_ok=True)
        
        yield event.plain_result("正在生成字体列表...")
        
        try:
            await asyncio.get_event_loop().run_in_executor(None, lambda: asyncio.run(render()))
            # 缓存生成的图片
            shutil.copy(str(img_path), str(cached_img_path))
            if self.listall_menu_image_send_mode == "image":
                yield event.image_result(str(cached_img_path))
            elif self.listall_menu_image_send_mode == "file":
                # yield event.plain_result("正在发送字体列表图片（文件方式）...")
                await event.send(event.chain_result([CompFile(file=str(cached_img_path), name="font_list.png")]))
            elif self.listall_menu_image_send_mode == "zipfile":
                # yield event.plain_result("正在发送字体列表图片（压缩包方式）...")
                zip_path = self.cache_path / f"font_lists.zip"
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    zf.write(cached_img_path, arcname="font_list.png")
                # yield event.chain_result(CompFile(file=str(zip_path), name=""))
                await event.send(event.chain_result([CompFile(file=str(zip_path), name="font_list.zip")]))
        except Exception as e:
            logger.exception(f"生成字体列表失败: {e}")
            yield event.plain_result(f"生成失败: {e}")
        finally:
            if img_path.exists():
                img_path.unlink(missing_ok=True)


    async def _render_and_send_list_page(self, event, page, sorted_fonts, total_pages):
        """渲染 list 命令的某一页为图片并发送（带缓存）"""
        font_samples_dir = self.data_path / "font_samples"
        font_samples_dir.mkdir(parents=True, exist_ok=True)
        
        sample_text = "你好 123Abc"
        start_idx = (page - 1) * self.fonts_per_page
        end_idx = min(start_idx + self.fonts_per_page, len(sorted_fonts))
        page_fonts = sorted_fonts[start_idx:end_idx]
        
        # 收集需要渲染的字体任务（仅当前页）
        render_tasks = []
        for idx, (font_name, font_path) in enumerate(page_fonts):
            global_idx = start_idx + idx
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            if not font_img_path.exists():
                render_tasks.append((global_idx, font_name, font_path, font_img_path))
        
        # 并发渲染缺失的字体示例图
        if render_tasks:
            logger.debug(f"[DEBUG] list 命令需要渲染 {len(render_tasks)} 个字体示例图")
            semaphore = asyncio.Semaphore(self.max_concurrent_font_samples)
            
            async def render_font_sample(task_global_idx, task_font_name, task_font_path, task_font_img_path):
                async with semaphore:
                    try:
                        logger.debug(f"[DEBUG] 渲染字体示例：{task_font_name}")
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: render_text_sync(
                                text=sample_text,
                                font_path=str(task_font_path),
                                output_path=str(task_font_img_path)
                            )
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"[WARN] 渲染字体 {task_font_name} 失败：{e}")
                        return False
            
            await asyncio.gather(*[
                render_font_sample(tidx, tname, tpath, timgpath)
                for tidx, tname, tpath, timgpath in render_tasks
            ])
        
        # 构建 HTML 行（网格布局）
        columns = self.font_list_columns
        font_rows = []
        
        for idx, (font_name, font_path) in enumerate(page_fonts):
            global_idx = start_idx + idx
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            
            if not font_img_path.exists():
                continue
            
            is_default = " (默认)" if font_name == self.default_font else ""
            rel_path = f"../font_samples/{font_img_path.name}"
            
            # 每行开始新行
            if idx % columns == 0:
                font_rows.append('<tr>')
            
            # 添加单个字体单元格（保留字体编号、昵称、预览图）
            font_rows.append(f"""<td class=\"font-cell\">
                <div style="display:flex; flex-direction: row;">
                    <div class=\"font-index\">{global_idx + 1}</div>
                    <div class=\"font-name\">{font_name}{is_default}</div>
                </div>
                <div class=\"font-sample\"><img style="width:200px;" src=\"{rel_path}\"></div>
            </td>""")
            
            # 每行结束或最后一个字体时闭合行
            if (idx + 1) % columns == 0 or idx == len(page_fonts) - 1:
                font_rows.append('</tr>')
        
        # 页眉和页尾提示
        font_rows.insert(0, f'''<tr>
            <td colspan="{columns}" class="page-break">页 {page}/{total_pages}</td>
        </tr>''')
        font_rows.append(f'''<tr>
            <td colspan="{columns}" class="page-tip" style="text-align:center">使用 texttool list <页码> 切换页面</td>
        </tr>''')
        
        # 计算缓存指纹（基于当前页字体）
        cache_key_parts = [str(page), str(total_pages), str(self.fonts_per_page), self.default_font]
        for font_name, font_path in page_fonts:
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            font_mtime = font_path.stat().st_mtime
            sample_mtime = font_img_path.stat().st_mtime if font_img_path.exists() else 0
            cache_key_parts.append(f"{font_name}:{font_mtime}:{sample_mtime}")
        
        cache_key = hashlib.md5("".join(cache_key_parts).encode()).hexdigest()
        cached_img_path = self.cache_path / f"fontlist_page_{page}_cached_{cache_key}.png"
        
        # 检查缓存是否有效
        if cached_img_path.exists():
            logger.debug(f"[DEBUG] 使用缓存的 list 第{page}页图片：{cached_img_path}")
            await self._send_menu_image(event, cached_img_path, self.list_menu_image_send_mode)
            return
        
        # 构建 HTML
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ background: #FFFFFF; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td {{ background: #FFFFFF; }}
        .font-cell {{
            text-align: center;
            vertical-align: top;
            padding: 8px;
            border-right: 1px solid #ddd;
            border-bottom: 1px solid #ddd;
            width: {100 // columns}%;
        }}
        .font-index {{
            font-family: sans-serif;
            font-size: 16px;
            padding: 4px;
            text-align: center;
            color: #888;
        }}
        .font-name {{
            font-family: sans-serif;
            font-size: 14px;
            padding: 4px;
            color: #bbb;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            width:100px;
        }}
        .font-sample {{
            padding: 8px;
            text-align: center;
            vertical-align: middle;
        }}
        .font-sample img {{
            display: inline-block;
            max-width: 100%;
            height: auto;
        }}
        .page-break {{
            font-family: sans-serif;
            font-size: 20px;
            text-align: left;
            padding: 12px;
            font-weight: bold;
            color: #0066cc;
        }}
        .page-tip {{
            font-family: sans-serif;
            font-size: 14px;
            text-align: center;
            padding: 15px;
            color: #666;
        }}
        h1 {{
            font-family: sans-serif;
            font-size: 32px;
            margin-bottom: 20px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <h1>可用字体列表 - 第{page}页</h1>
    <small>每页 {len(page_fonts)} 种字体</small>
    <table>
        {"".join(font_rows)}
    </table>
</body>
</html>"""
        
        # 生成图片
        uid = hashlib.sha256(str(event.get_sender_id()).encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        img_path = self.cache_path / f"fontlist_page_{page}_{uid}_{ts}.png"
        
        from playwright.async_api import async_playwright
        
        async def render():
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page_obj = await browser.new_page(viewport={"width": 1200, "height": 800})
                html_path = self.cache_path / f"fontlist_page_{page}_{uid}_{ts}.html"
                html_path.write_text(html_content, encoding="utf-8")
                await page_obj.goto(f"file://{html_path.absolute()}")
                await page_obj.wait_for_timeout(1000)
                await page_obj.screenshot(path=str(img_path), full_page=True, omit_background=False)
                await browser.close()
                if html_path.exists():
                    html_path.unlink(missing_ok=True)
        
        # 检查缓存是否有效
        if cached_img_path.exists():
            logger.debug(f"[DEBUG] 使用缓存的 list 第{page}页图片：{cached_img_path}")
            await self._send_menu_image(event, cached_img_path, self.list_menu_image_send_mode)
            return
        
        # 发送提示消息
        await event.send(event.plain_result(f"正在生成第{page}页字体列表..."))
        
        try:
            await asyncio.get_event_loop().run_in_executor(None, lambda: asyncio.run(render()))
            shutil.copy(str(img_path), str(cached_img_path))
            await self._send_menu_image(event, cached_img_path, self.list_menu_image_send_mode)
        except Exception as e:
            logger.exception(f"生成字体列表第{page}页失败：{e}")
            await event.send(event.plain_result(f"生成失败：{e}"))
        finally:
            if img_path.exists():
                img_path.unlink(missing_ok=True)

    async def _send_menu_image(self, event, img_path, send_mode):
        """根据发送模式发送菜单图片"""
        if send_mode == "image":
            await event.send(event.chain_result([CompImage(file=str(img_path))]))
        elif send_mode == "file":
            await event.send(event.chain_result([CompFile(file=str(img_path), name="font_list.png")]))
        elif send_mode == "zipfile":
            zip_path = self.cache_path / f"font_lists.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.write(img_path, arcname="font_list.png")
            await event.send(event.chain_result([CompFile(file=str(zip_path), name="font_list.zip")]))

    @texttool.command("list")
    async def list_fonts(self, event: AstrMessageEvent):
        """列出字体，后面加数字换页"""
        raw = event.message_str.strip()
        prefix = "texttool list"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        page = 1
        if raw:
            try:
                page = int(raw)
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码必须是数字，使用方式: texttool list [页码]")
                return
        
        fonts = self._scan_fonts()
        if not fonts:
            yield event.plain_result("未找到任何字体文件，请在插件目录的 fonts 文件夹中添加字体文件")
            return
        
        sorted_fonts = sorted(fonts.items())
        total_fonts = len(sorted_fonts)
        total_pages = (total_fonts + self.fonts_per_page - 1) // self.fonts_per_page
        
        if page > total_pages:
            yield event.plain_result(f"页码超出范围，总共 {total_pages} 页")
            return
        
        # 检查发送模式，如果不为 text，则渲染为图片
        if self.list_menu_image_send_mode != "text":
            # 渲染当前页为图片（带缓存）
            await self._render_and_send_list_page(event, page, sorted_fonts, total_pages)
            return
        
        start_idx = (page - 1) * self.fonts_per_page
        end_idx = min(start_idx + self.fonts_per_page, total_fonts)
        
        msg_lines = []
        msg_lines.append(f"可用字体列表 (第 {page}/{total_pages} 页，共 {total_fonts} 种字体):")
        msg_lines.append("=" * 40)
        
        for i in range(start_idx, end_idx):
            font_name, font_path = sorted_fonts[i]
            idx = i + 1
            if font_name == self.default_font:
                msg_lines.append(f"{idx:2d}. {font_name} (默认字体)")
            else:
                msg_lines.append(f"{idx:2d}. {font_name}")
        
        msg_lines.append("=" * 40)
        
        if total_pages > 1:
            page_info = []
            for p in range(1, total_pages + 1):
                if p == page:
                    page_info.append(f"[{p}]")
                else:
                    page_info.append(str(p))
            
            msg_lines.append(f"页码: {' '.join(page_info)}")
            msg_lines.append(f"查看其他页: texttool list <页码>")
        
        msg_lines.append("")
        msg_lines.append("使用方式:")
        msg_lines.append("  texttool generate font:字体名称 文本内容")
        msg_lines.append("  texttool listall - 查看完整列表")
        
        yield event.plain_result("\n".join(msg_lines))

    @texttool.command("get")
    async def get_font(self, event: AstrMessageEvent):
        """获取字体源文件"""
        # 检查是否允许获取字体
        if not self.allow_get_font:
            yield event.plain_result("管理员未开启获取字体功能，无法执行此操作。")
            return
        
        raw = event.message_str.strip()
        prefix = "texttool get"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        if not raw:
            yield event.plain_result("请提供字体 ID，使用方式：texttool get [字体 ID]")
            return
        
        try:
            font_id = int(raw)
        except ValueError:
            yield event.plain_result("字体 ID 必须是数字，使用方式：texttool get [字体 ID]")
            return
        
        fonts = self._scan_fonts()
        if not fonts:
            yield event.plain_result("未找到任何字体文件")
            return
        
        sorted_fonts = sorted(fonts.items())
        total_fonts = len(sorted_fonts)
        
        if font_id < 1 or font_id > total_fonts:
            yield event.plain_result(f"字体 ID 超出范围 (1-{total_fonts})，请使用 texttool list 查看可用字体")
            return
        
        font_name, font_path = sorted_fonts[font_id - 1]
        
        if not font_path.exists():
            yield event.plain_result(f"字体文件不存在：{font_path}")
            return
        
        # 发送字体文件
        yield event.chain_result([CompFile(file=str(font_path), name=font_path.name)])

    @texttool.command("updatecache")
    async def updatecache(self, event: AstrMessageEvent):
        """强制更新缓存"""
        raw = event.message_str.strip()
        prefix = "texttool updatecache"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        if not raw:
            yield event.plain_result("用法:\n  texttool updatecache all - 更新所有缓存\n  texttool updatecache list [页码|all] - 更新 list 菜单缓存\n  texttool updatecache listall - 更新 listall 菜单缓存\n  texttool updatecache font [编号|all] - 更新字体示例缓存")
            return
        
        parts = raw.split()
        cmd_type = parts[0].lower()
        
        if cmd_type == "all":
            # 更新所有缓存
            yield event.plain_result("正在更新所有缓存，可能需要较长时间...")
            await self._clear_list_cache()
            await self._clear_font_samples_cache()
            yield event.plain_result("所有缓存已清除，下次使用时会自动重新生成")
            return
        
        elif cmd_type == "list":
            if len(parts) < 2:
                yield event.plain_result("用法：texttool updatecache list [页码|all]\n  页码：更新指定页缓存\n  all：更新所有页缓存")
                return
            
            page_arg = parts[1].lower()
            fonts = self._scan_fonts()
            if not fonts:
                yield event.plain_result("未找到任何字体文件")
                return
            
            sorted_fonts = sorted(fonts.items())
            total_fonts = len(sorted_fonts)
            total_pages = (total_fonts + self.fonts_per_page - 1) // self.fonts_per_page
            
            if page_arg == "all":
                # 更新所有页
                yield event.plain_result(f"正在清除 list 命令的所有 {total_pages} 页缓存...")
                await self._clear_list_cache(all_pages=True)
                yield event.plain_result(f"list 命令所有页缓存已清除，共 {total_pages} 页")
            else:
                try:
                    page_num = int(page_arg)
                    if page_num < 1 or page_num > total_pages:
                        yield event.plain_result(f"页码超出范围 (1-{total_pages})")
                        return
                    yield event.plain_result(f"正在清除 list 命令第 {page_num} 页缓存...")
                    await self._clear_list_cache(page=page_num)
                    yield event.plain_result(f"list 命令第 {page_num} 页缓存已清除")
                except ValueError:
                    yield event.plain_result("页码必须是数字或 all")
            return
        
        elif cmd_type == "listall":
            yield event.plain_result("listall 命令字体示例缓存忘了怎么写了")
            return
        
        elif cmd_type == "font":
            if len(parts) < 2:
                yield event.plain_result("用法：texttool updatecache font [编号|all]\n  编号：更新指定字体示例缓存\n  all：更新所有字体示例缓存")
                return
            
            font_arg = parts[1].lower()
            fonts = self._scan_fonts()
            if not fonts:
                yield event.plain_result("未找到任何字体文件")
                return
            
            sorted_fonts = sorted(fonts.items())
            
            if font_arg == "all":
                yield event.plain_result(f"正在清除所有 {len(sorted_fonts)} 个字体示例缓存...")
                await self._clear_font_samples_cache()
                yield event.plain_result(f"所有字体示例缓存已清除，共 {len(sorted_fonts)} 个字体")
            else:
                try:
                    font_idx = int(font_arg) - 1
                    if font_idx < 0 or font_idx >= len(sorted_fonts):
                        yield event.plain_result(f"字体编号超出范围 (1-{len(sorted_fonts)})")
                        return
                    
                    font_name, font_path = sorted_fonts[font_idx]
                    font_samples_dir = self.data_path / "font_samples"
                    font_img_path = font_samples_dir / f"{font_path.stem}.png"
                    
                    if font_img_path.exists():
                        font_img_path.unlink()
                        yield event.plain_result(f"字体 '{font_name}' (编号{font_idx+1}) 的示例缓存已清除")
                    else:
                        yield event.plain_result(f"字体 '{font_name}' (编号{font_idx+1}) 没有缓存")
                except ValueError:
                    yield event.plain_result("字体编号必须是数字或 all")
            return
        
        else:
            yield event.plain_result(f"未知的命令类型：{cmd_type}\n使用 texttool updatecache 查看帮助")

    async def _clear_list_cache(self, page=None, all_pages=False):
        """清除 list 命令的缓存图片"""
        import glob
        pattern = str(self.cache_path / "fontlist_page_*.png")
        for cached_file in glob.glob(pattern):
            path = Path(cached_file)
            if all_pages:
                path.unlink(missing_ok=True)
            elif page is not None:
                if f"fontlist_page_{page}_" in path.name:
                    path.unlink(missing_ok=True)

    async def _clear_font_samples_cache(self):
        """清除字体示例图缓存"""
        font_samples_dir = self.data_path / "font_samples"
        if font_samples_dir.exists():
            for img_file in font_samples_dir.glob("*.png"):
                img_file.unlink(missing_ok=True)

    @texttool.command("task")
    async def task(self, event: AstrMessageEvent):
        """查看当前任务队列状态"""
        qsize = self.queue.qsize()
        yield event.plain_result(f"当前队列长度: {qsize}/{self.max_task}")

    @texttool.command("generate")
    async def generate(self, event: AstrMessageEvent):
        """生成文本图片，参数详见 texttool pm"""
        group_id = event.get_group_id()
        if group_id:
            if str(group_id) in self.blacklist:
                yield event.plain_result(self.blacklist_notice)
                logger.info(f"群 {group_id} 在黑名单中，拒绝执行 generate")
                return
        
        raw = event.message_str.strip()
        prefix = "texttool generate"

        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()

        if not raw:
            yield event.plain_result("用法: texttool generate font:字体名 文本内容")
            return

        params, content = self._parse_params(raw)

        # 如果解析后没有正文，当作普通文本处理
        if not content:
            content = raw

        mode = params.pop("mode", "single")
        tokens = self._split_content(content, mode)

        total_chars = sum(len(t) for t in tokens)

        if total_chars > self.max_chars_per_task:
            yield event.plain_result(f"文本过长，最大支持 {self.max_chars_per_task}")
            return

        if len(tokens) > self.max_images_per_task:
            yield event.plain_result(f"图片数量过多，最大支持 {self.max_images_per_task}")
            return
        
        # 提取扩展参数
        ext = params.pop("ext", None)
        
        try:
            await self._process_and_send(event, params, tokens, ext=ext)
        except Exception as e:
            logger.exception(f"生成图片失败: {e}")
            yield event.plain_result(f"生成失败: {e}")
        

    # =======================
    # 核心处理
    # =======================

    async def _process_and_send(self, event, params, tokens, ext=None):

        uid = hashlib.sha256(str(event.get_sender_id()).encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        chain = None # 保留
        folder = self.cache_path / f"{uid}_{ts}"
        folder.mkdir(parents=True, exist_ok=True)

        font_name = params.pop("font", self.default_font)
        font_path = self._resolve_font(font_name)

        # 将扩展参数加入渲染参数
        if ext:
            params["ext"] = ext

        # 使用异步并发渲染
        images = await _render_batch_async(
            tokens=tokens,
            folder=folder,
            font_path=font_path,
            params=params,
            max_concurrent=self.max_concurrent_renders,
        )

        zip_path: Optional[Path] = None

        try:
            if len(images) == 1:
                if self.single_image_send_by_file:
                    chain = [CompFile(file=str(images[0]), name=images[0].name)] 
                else:
                    chain = [CompImage(file=str(images[0]))]
                try:
                    await event.send(event.chain_result(chain))
                except Exception as e:
                    logger.warning(f"直接发送图片失败，尝试文件发送: {e}")
                    chain = [CompFile(file=str(images[0]), name=images[0].name)]
                    try:
                        await event.send(event.chain_result(chain))
                    except Exception as e2:
                        logger.warning(f"文件发送失败: {e2}")
                        await event.send(event.plain_result(f"图片/文件发送均失败: \n第一轮报错: {e}\n第二轮报错: {e2}"))
                
            else:
                zip_path = folder.with_suffix(".zip")
                self._zip(folder, zip_path)
                await event.send(
                    event.chain_result([
                        CompFile(file=str(zip_path), name=zip_path.name)
                    ])
                )
                await asyncio.sleep(10)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            if zip_path and zip_path.exists():
                zip_path.unlink(missing_ok=True)

    # =======================
    # 工具函数
    # =======================

    def _scan_fonts(self) -> Dict[str, Path]:
        fonts = {}
        for f in self.fonts_dir.glob("*"):
            if f.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                fonts[f.stem] = f
        return fonts

    def _resolve_font(self, font_name: str) -> Path:
        font_name = str(font_name)
        fonts = self._scan_fonts()

        # 1. 精确匹配
        if font_name in fonts:
            return fonts[font_name]

        # 2. 忽略大小写匹配
        for name, path in fonts.items():
            if name.lower() == font_name.lower():
                return path

        # 3. 编号匹配（序号从 1 开始）
        if font_name.isdigit():
            sorted_fonts = sorted(fonts.items(), key=lambda x: x[0])
            index = int(font_name) - 1  # 转换为 0 索引
            if 0 <= index < len(sorted_fonts):
                return sorted_fonts[index][1]

        raise ValueError(f"未找到字体: {font_name}")

    def _parse_color(self, value: str) -> Tuple[int, int, int, int]:
        v = value.lstrip("#")

        if len(v) == 6:
            r, g, b = v[0:2], v[2:4], v[4:6]
            a = "FF"
        elif len(v) == 8:
            r, g, b, a = v[0:2], v[2:4], v[4:6], v[6:8]
        else:
            raise ValueError("非法颜色")

        return (int(r, 16), int(g, 16), int(b, 16), int(a, 16))

    def _parse_params(self, text: str) -> Tuple[Dict[str, Any], str]:

        params = {}
        content_parts = []
        
        i = 0
        n = len(text)
        
        while i < n:
            # 跳过空白
            while i < n and text[i] == " ":
                i += 1
            if i >= n:
                break
                
            # 检查是否是参数格式 (key:value)
            if text[i].isalnum() or text[i] == "_":
                # 找到冒号
                colon_idx = text.find(":", i)
                if colon_idx != -1:
                    key = text[i:colon_idx]
                    value_start = colon_idx + 1
                    
                    # 检查是否带引号
                    if value_start < n and text[value_start] == '"':
                        # 找到闭合引号
                        value_end = text.find('"', value_start + 1)
                        if value_end == -1:
                            # 没找到闭合引号，剩下的都当文本
                            value = text[value_start:]
                            i = n
                        else:
                            value = text[value_start + 1:value_end]
                            i = value_end + 1
                    else:
                        # 读取到下一个空格为止
                        value_end = text.find(" ", value_start)
                        if value_end == -1:
                            value = text[value_start:]
                            i = n
                        else:
                            value = text[value_start:value_end]
                            i = value_end
                    
                    # 检查是否在允许列表
                    if key in self.ALLOWED_PARAMS:
                        try:
                            if key in ("text_color", "bg_color", "stroke_color"):
                                parsed = self._parse_color(value)
                            else:
                                parsed = self._cast(value)
                            self._validate_param(key, parsed)
                            params[key] = parsed
                        except Exception:
                            content_parts.append(f"{key}:{value}")
                    else:
                        content_parts.append(f"{key}:{value}")
                    continue
            
            # 不是参数，当作文本
            # 读取到下一个空格为止
            space_idx = text.find(" ", i)
            if space_idx == -1:
                content_parts.append(text[i:])
                break
            else:
                content_parts.append(text[i:space_idx])
                i = space_idx + 1

        content = " ".join(content_parts)
        return params, content

    def _cast(self, v: str) -> Union[int, float, str]:
        try:
            return int(v)
        except:
            pass
        try:
            return float(v)
        except:
            pass
        return v

    def _split_content(self, text: str, mode: str) -> List[str]:

        if mode == "char":
            return [c for c in text if not c.isspace()]
        if mode == "word":
            return [w for w in text.split() if w]
        if mode == "line":
            return [l for l in text.splitlines() if l.strip()]
        if mode == "token":
            return [t for t in text.split("|") if t.strip()]
        if mode == "article":
            # 保留完整空格和换行
            return [text]

        return [text.strip()]

    def _zip(self, folder: Path, zip_path: Path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in folder.iterdir():
                z.write(f, f.name)
                
    def _validate_param(self, key: str, value: Any):
        
        """
        此处的判断并不用于拦截某个值的传入
        而是用于判断是否为参数，渲染的时候异常参数已经返回在用户的结果里面了
        如果用户输入的不是参数格式，而是普通文本，我们也应该保留它，尊重用户意愿
        """
        
        if key == "canvas_height":
            if value <= 0:
                raise ValueError

        elif key == "canvas_width":
            if value is not None and value <= 0:
                raise ValueError

        elif key == "font_size":
            if value <= 0:
                raise ValueError

        elif key == "dpi":
            if value <= 0:
                raise ValueError

        elif key == "padding":
            if value < 0:
                raise ValueError

        elif key == "x_offset_ratio":
            if not 0 <= value <= 1:
                raise ValueError

        elif key == "y_offset_ratio":
            if not 0 <= value <= 1:
                raise ValueError
