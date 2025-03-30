#!/usr/bin/env python3
import gi, subprocess, time, sys, os, configparser, json
gi.require_version("Gtk", "3.0")
gi.require_version("Wnck", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, GdkPixbuf, Gdk, Wnck, GdkX11

def load_config():
    config = configparser.ConfigParser()
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        home = os.path.expanduser("~")
        config_file = os.path.join(home, ".config", "smartscreenshot", "smartscreenshot.ini")
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    if os.path.exists(config_file):
        config.read(config_file)
    else:
        config["General"] = {
            "override_width": "",
            "override_height": "",
            "main_border_width": "10",
            "image_viewer": "xdg-open",
            "thumbnail_scale_divisor": "4",
            "global_preview_scale_fraction": "0.5",
            "container_border": "2",
            "capture_delay": "0.5",
            "scripts_config": os.path.join(os.path.expanduser("~"), ".config", "smartscreenshot", "scripts.json")
        }
        with open(config_file, "w") as f:
            config.write(f)
    if "container_border" not in config["General"]:
        config["General"]["container_border"] = "2"
    if "capture_delay" not in config["General"]:
        config["General"]["capture_delay"] = "0.5"
    if "image_viewer" not in config["General"]:
        config["General"]["image_viewer"] = "xdg-open" 
    if "scripts_config" not in config["General"]:
        config["General"]["scripts_config"] = os.path.join(os.path.expanduser("~"), ".config", "smartscreenshot", "scripts.json")
    return config, config_file

def load_scripts_config(config):
    scripts_path = config["General"].get("scripts_config")
    if not os.path.exists(scripts_path):
        default_scripts = {
            "scripts": [
                {
                    "name": "Generic Script",
                    "path": "process_image.py",
                    "parameters": [
                        {"label": "Custom Parameter", "default": "1.0"}
                    ]
                }
            ]
        }
        os.makedirs(os.path.dirname(scripts_path), exist_ok=True)
        with open(scripts_path, "w") as f:
            json.dump(default_scripts, f, indent=4)
        return default_scripts
    else:
        with open(scripts_path, "r") as f:
            try:
                scripts_conf = json.load(f)
            except json.JSONDecodeError:
                scripts_conf = {"scripts": []}
        return scripts_conf

class ScreenshotApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Screenshot App")
        self.set_default_size(1000, 700)

        self.config, self.config_file = load_config()
        print(f"Using config file: {self.config_file}")
        self.scripts_conf = load_scripts_config(self.config)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor()
        geometry = monitor.get_geometry()
        system_width = geometry.width
        system_height = geometry.height

        try:
            override_width = int(self.config["General"].get("override_width", ""))
            override_height = int(self.config["General"].get("override_height", ""))
            self.screen_width = override_width if override_width > 0 else system_width
            self.screen_height = override_height if override_height > 0 else system_height
        except ValueError:
            self.screen_width = system_width
            self.screen_height = system_height

        print(f"Using resolution: {self.screen_width} x {self.screen_height}")

        try:
            self.main_border_width = int(self.config["General"].get("main_border_width", "10"))
        except ValueError:
            self.main_border_width = 10

        try:
            self.thumb_divisor = int(self.config["General"].get("thumbnail_scale_divisor", "4"))
            if self.thumb_divisor <= 0:
                self.thumb_divisor = 4
        except ValueError:
            self.thumb_divisor = 4

        try:
            self.preview_fraction = float(self.config["General"].get("global_preview_scale_fraction", "0.5"))
            if self.preview_fraction <= 0 or self.preview_fraction > 1:
                self.preview_fraction = 0.5
        except ValueError:
            self.preview_fraction = 0.5

        try:
            self.container_border = int(self.config["General"].get("container_border", "2"))
        except ValueError:
            self.container_border = 2

        try:
            self.capture_delay = float(self.config["General"].get("capture_delay", "0.5"))
        except ValueError:
            self.capture_delay = 0.5

        self.set_default_size(self.screen_width // 2, self.screen_height // 2)

        self.last_pixbuf = None
        self.last_capture_name = "None"

        notebook = Gtk.Notebook()
        self.add(notebook)

        # --- Tab: Window Capture ---
        window_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        window_box.set_border_width(self.main_border_width)
        window_frame = Gtk.Frame()
        window_frame.set_shadow_type(Gtk.ShadowType.IN)
        window_frame.set_border_width(self.container_border)
        window_frame.add(window_box)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        window_box.pack_start(button_box, False, False, 0)

        capture_full_btn = Gtk.Button(label="Capture Full Screen")
        capture_full_btn.connect("clicked", self.on_capture_full_clicked)
        button_box.pack_start(capture_full_btn, False, False, 0)

        refresh_btn = Gtk.Button(label="Refresh Window List")
        refresh_btn.connect("clicked", lambda b: self.populate_window_list())
        button_box.pack_start(refresh_btn, False, False, 0)

        # New: Upload Image button.
        upload_btn = Gtk.Button(label="Upload Image")
        upload_btn.connect("clicked", self.on_upload_image)
        button_box.pack_start(upload_btn, False, False, 0)

        scrolled_list = Gtk.ScrolledWindow()
        scrolled_list.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_list.set_min_content_height(self.screen_height // 2)
        window_box.pack_start(scrolled_list, True, True, 0)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(2)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_row_spacing(10)
        self.flowbox.set_column_spacing(10)
        scrolled_list.add(self.flowbox)
        self.populate_window_list()

        notebook.append_page(window_frame, Gtk.Label(label="Window Capture"))

        # --- Tab: Scripts ---
        script_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        script_paned.connect("size-allocate", self.on_script_paned_allocate)

        self.script_flow = Gtk.FlowBox()
        self.script_flow.set_valign(Gtk.Align.START)
        self.script_flow.set_max_children_per_line(2)
        self.script_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.script_flow.set_row_spacing(10)
        self.script_flow.set_column_spacing(10)
        scrolled_scripts = Gtk.ScrolledWindow()
        scrolled_scripts.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_scripts.add(self.script_flow)

        script_top_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        script_top_box.pack_start(scrolled_scripts, True, True, 0)
        preview_proc_btn = Gtk.Button(label="Preview Processed Image")
        preview_proc_btn.connect("clicked", self.on_preview_processed)
        script_top_box.pack_start(preview_proc_btn, False, False, 0)
        script_paned.pack1(script_top_box, True, False)

        # Load script sections from the external JSON config.
        scripts = self.scripts_conf.get("scripts", [])
        if not scripts:
            scripts = [{
                "name": "Generic Script",
                "path": "process_image.py",
                "parameters": [{"label": "Custom Parameter", "default": "1.0"}]
            }]
        for script in scripts:
            name = script.get("name", "Unnamed Script")
            path = script.get("path", "")
            params_list = script.get("parameters", [])
            parameters = []
            for param in params_list:
                label = param.get("label", "Param")
                default = param.get("default", "")
                parameters.append((label, default))
            section = self.create_script_section(script_title=name, script_name=path, parameters=parameters)
            self.script_flow.add(section)

        preview_scrolled = Gtk.ScrolledWindow()
        preview_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_frame = Gtk.Frame(label="Last Captured Image")
        preview_frame.set_shadow_type(Gtk.ShadowType.IN)
        preview_frame.set_margin_top(10)
        preview_scrolled.add(preview_frame)
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        preview_box.set_border_width(self.main_border_width)
        preview_frame.add(preview_box)
        self.last_capture_label = Gtk.Label(label="No capture yet")
        self.last_capture_label.set_xalign(0)
        preview_box.pack_start(self.last_capture_label, False, False, 0)
        self.global_preview = Gtk.Image()
        self.global_preview.set_hexpand(True)
        self.global_preview.set_vexpand(True)
        preview_box.pack_start(self.global_preview, True, True, 0)
        script_paned.pack2(preview_scrolled, False, False)
        notebook.append_page(script_paned, Gtk.Label(label="Scripts"))

        self.show_all()

    def on_script_paned_allocate(self, widget, allocation):
        widget.set_position(allocation.height // 2)

    def create_script_section(self, script_title, script_name, parameters):
        section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        section_box.set_border_width(self.main_border_width)
        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{script_title}</b>")
        title_label.set_xalign(0)
        section_box.pack_start(title_label, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        section_box.pack_start(grid, False, False, 0)
        section_box.param_entries = []
        for i, (param_label, default) in enumerate(parameters):
            lbl = Gtk.Label(label=param_label + ":")
            lbl.set_xalign(1)
            entry = Gtk.Entry()
            entry.set_text(default)
            section_box.param_entries.append(entry)
            grid.attach(lbl, 0, i, 1, 1)
            grid.attach(entry, 1, i, 1, 1)
        btn = Gtk.Button(label=f"Run {script_title}")
        btn.connect("clicked", self.on_run_script, script_name, section_box)
        section_box.pack_start(btn, False, False, 0)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.set_border_width(self.container_border)
        frame.add(section_box)
        return frame

    def update_global_preview(self, pixbuf, capture_name):
        self.last_pixbuf = pixbuf
        self.last_capture_name = capture_name
        self.last_capture_label.set_text(f"Last Capture: {capture_name}")
        if pixbuf:
            orig_width = pixbuf.get_width()
            target_width = int(self.screen_width * self.preview_fraction)
            scale_factor = target_width / float(orig_width) if orig_width else 1
            new_height = int(pixbuf.get_height() * scale_factor)
            scaled = pixbuf.scale_simple(target_width, new_height, GdkPixbuf.InterpType.HYPER)
            self.global_preview.set_from_pixbuf(scaled)

    def show_preview_dialog(self, pixbuf, title="Preview"):
        # Instead of an internal preview dialog, we open with the system's default image viewer.
        temp_path = "temp_preview.png"
        pixbuf.savev(temp_path, "png", [], [])
        try:
            image_viewer = self.config["General"].get("image_viewer", "xdg-open")
            subprocess.run([image_viewer, temp_path])
        except Exception as e:
            print("Error opening external viewer:", e)
        return None

    def on_capture_full_clicked(self, button):
        self.hide()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(self.capture_delay)
        root_window = Gdk.get_default_root_window()
        width = root_window.get_width()
        height = root_window.get_height()
        pb = Gdk.pixbuf_get_from_window(root_window, 0, 0, width, height)
        self.show()
        if not pb:
            print("Screenshot failed (pb is None). Are you on X11?")
            return
        pb.savev("screenshot.png", "png", [], [])
        self.update_global_preview(pb, "Full Screen")
        self.show_preview_dialog(pb, title="Full Screen Preview")

    def populate_window_list(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        screen = Wnck.Screen.get_default()
        screen.force_update()
        windows = screen.get_windows()
        for win in windows:
            title = win.get_name()
            if title and not win.is_minimized():
                xid = win.get_xid()
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
                card_frame = Gtk.Frame()
                card_frame.set_shadow_type(Gtk.ShadowType.IN)
                card_frame.set_border_width(self.container_border)
                inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
                card_frame.add(inner_box)
                btn = Gtk.Button(label=title)
                btn.xid = xid
                btn.connect("clicked", self.on_window_button_clicked)
                inner_box.pack_start(btn, False, False, 0)
                display = Gdk.Display.get_default()
                gdk_win = GdkX11.X11Window.foreign_new_for_display(display, xid)
                thumb = None
                if gdk_win:
                    geom = gdk_win.get_geometry()
                    w_width, w_height = geom.width, geom.height
                    pb = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w_width, w_height)
                    if pb:
                        new_width = self.screen_width // self.thumb_divisor
                        scale_factor = new_width / float(w_width) if w_width else 1
                        new_height = int(w_height * scale_factor) if w_height else 0
                        if new_width > 0 and new_height > 0:
                            thumb = pb.scale_simple(new_width, new_height, GdkPixbuf.InterpType.HYPER)
                if not thumb:
                    thumb = win.get_icon()
                image_widget = Gtk.Image()
                if thumb:
                    image_widget.set_from_pixbuf(thumb)
                else:
                    image_widget.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
                inner_box.pack_start(image_widget, False, False, 0)
                vbox.pack_start(card_frame, True, True, 0)
                self.flowbox.add(vbox)
        self.flowbox.show_all()

    def on_window_button_clicked(self, button):
        xid = button.xid
        display = Gdk.Display.get_default()
        gdk_win = GdkX11.X11Window.foreign_new_for_display(display, xid)
        if not gdk_win:
            print("Failed to get Gdk.Window for XID", xid)
            return
        geom = gdk_win.get_geometry()
        width, height = geom.width, geom.height
        self.hide()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(self.capture_delay)
        pb = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, width, height)
        self.show()
        if not pb:
            print("Failed to capture window with XID", xid)
            return
        pb.savev("window_screenshot.png", "png", [], [])
        self.update_global_preview(pb, button.get_label())
        self.show_preview_dialog(pb, title="Window Capture Preview")

    def on_run_script(self, button, script_name, container):
        if self.last_pixbuf is None:
            print("No capture available!")
            return
        temp_input = "last_capture.png"
        self.last_pixbuf.savev(temp_input, "png", [], [])
        params = []
        if container is not None and hasattr(container, "param_entries"):
            params = [entry.get_text() for entry in container.param_entries]
        subprocess.run(["python3", script_name, temp_input, "processed.png"] + params)
        try:
            pb_processed = GdkPixbuf.Pixbuf.new_from_file("processed.png")
            self.show_preview_dialog(pb_processed, title=f"{script_name} Preview")
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_image(pb_processed)
            clipboard.store()
        except Exception as e:
            print("Error loading processed image:", e)
        
    def on_preview_processed(self, button):
        if os.path.exists("processed.png"):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file("processed.png")
                self.show_preview_dialog(pb, title="Processed Image Preview")
                clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                clipboard.set_image(pb)
                clipboard.store()
            except Exception as e:
                print("Error loading processed image:", e)
        else:
            print("No processed image available.")

    def on_process_clicked(self, button):
        self.on_run_script(button, "process_image.py", None)

    def on_upload_image(self, button):
        dialog = Gtk.FileChooserDialog(
            title="Select an Image", parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                     Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        )
        filter_img = Gtk.FileFilter()
        filter_img.set_name("Image files")
        filter_img.add_mime_type("image/png")
        filter_img.add_mime_type("image/jpeg")
        filter_img.add_pattern("*.png")
        filter_img.add_pattern("*.jpg")
        filter_img.add_pattern("*.jpeg")
        dialog.add_filter(filter_img)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            selected_file = dialog.get_filename()
            print("Selected file:", selected_file)
            # Load the selected image.
            pb = GdkPixbuf.Pixbuf.new_from_file(selected_file)
            if pb:
                self.last_pixbuf = pb
                self.last_capture_name = os.path.basename(selected_file)
                self.update_global_preview(pb, self.last_capture_name)
            else:
                print("Failed to load the selected image.")
        dialog.destroy()

if __name__ == "__main__":
    app = ScreenshotApp()
    app.connect("destroy", Gtk.main_quit)
    Gtk.main()

