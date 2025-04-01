#!/usr/bin/env python3
import gi, subprocess, time, sys, os, configparser, json, re
gi.require_version("Gtk", "3.0")
gi.require_version("Wnck", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, GdkPixbuf, Gdk, Wnck, GdkX11

# Scan the scripts folder for subdirectories that contain a "main.py"
def get_available_scripts(scripts_root="scripts"):
    available = {}
    if os.path.exists(scripts_root) and os.path.isdir(scripts_root):
        for entry in os.listdir(scripts_root):
            subdir = os.path.join(scripts_root, entry)
            if os.path.isdir(subdir):
                main_py = os.path.join(subdir, "main.py")
                if os.path.exists(main_py):
                    available[entry] = main_py
    return available

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

# Blurring function using OpenCV
def blur_region(image, x, y, w, h, kernel_size, sigma):
    roi = image[y:y+h, x:x+w]
    blurred_roi = cv2.GaussianBlur(roi, (kernel_size, kernel_size), sigma)
    image[y:y+h, x:x+w] = blurred_roi

# Automatically blur sensitive regions based on OCR results
def auto_blur(image, kernel_size, sigma):
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    texts = data["text"]
    lefts = data["left"]
    tops = data["top"]
    widths = data["width"]
    heights = data["height"]
    print(f"Detected {len([t for t in texts if t.strip()])} non-empty text regions.")

    sensitive_labels = ["password", "api key", "secret", "token", "pwd", "pass", "credential", "key"]
    sensitive_patterns = [
        re.compile(r'[a-fA-F0-9]{32,}'),
        re.compile(r'[A-Za-z0-9-_]{20,}'),
        re.compile(r'eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+'),
        re.compile(r'[A-Za-z0-9+/]{20,}=*'),
    ]

    sensitive_boxes = []
    for i in range(len(texts)):
        text = texts[i].strip()
        if not text:
            continue
        lower_text = text.lower()
        if any(label in lower_text for label in sensitive_labels):
            print(f"Found potential sensitive label: '{texts[i]}'")
            sensitive_boxes.append((lefts[i], tops[i], widths[i], heights[i]))
            for j in range(i + 1, len(texts)):
                if abs(tops[j] - tops[i]) < 10 and texts[j].strip():
                    print(f"Blurring subsequent sensitive value: '{texts[j]}'")
                    sensitive_boxes.append((lefts[j], tops[j], widths[j], heights[j]))
                    break
        elif any(pattern.search(text) for pattern in sensitive_patterns):
            print(f"Found potential standalone secret: '{text}'")
            sensitive_boxes.append((lefts[i], tops[i], widths[i], heights[i]))
    print(f"Number of sensitive boxes detected: {len(sensitive_boxes)}")
    for box in sensitive_boxes:
        x, y, w, h = box
        blur_region(image, x, y, w, h, kernel_size, sigma)
    return image

# Import cv2 and pytesseract after function definitions
import cv2
import pytesseract

class ScreenshotApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Screenshot App")
        self.set_default_size(1000, 700)

        self.config, self.config_file = load_config()
        print(f"Using config file: {self.config_file}")
        self.scripts_conf = load_scripts_config(self.config)

        # Read screen resolution.
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

        # Store manual blur parameters from command-line (or default)
        if len(sys.argv) >= 4:
            try:
                self.manual_kernel = int(sys.argv[3])
                if self.manual_kernel % 2 == 0:
                    self.manual_kernel += 1
            except:
                self.manual_kernel = 99
        else:
            self.manual_kernel = 99
        if len(sys.argv) >= 5:
            try:
                self.manual_sigma = float(sys.argv[4])
            except:
                self.manual_sigma = 30
        else:
            self.manual_sigma = 30

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
        scripts_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scripts_vbox.set_border_width(self.main_border_width)
        # Script selector (combo box, extra parameters, and Run Script button)
        selector_box = self.create_script_selector()
        scripts_vbox.pack_start(selector_box, False, False, 0)
        # Add a button for Manual Blur via keyword input
        manual_blur_btn = Gtk.Button(label="Manual Blur (Enter Keyword)")
        manual_blur_btn.connect("clicked", self.show_keyword_dialog)
        scripts_vbox.pack_start(manual_blur_btn, False, False, 0)
        # Add preview frame for last capture.
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
        scripts_vbox.pack_start(preview_scrolled, True, True, 0)

        notebook.append_page(scripts_vbox, Gtk.Label(label="Scripts"))

        self.show_all()

    def create_script_selector(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label="Select Script:")
        box.pack_start(label, False, False, 0)
        
        combo = Gtk.ComboBoxText()
        available = get_available_scripts()
        for key, path in available.items():
            combo.append(key, path)
        if "secrets-handling" in available:
            combo.set_active_id("secrets-handling")
        else:
            combo.set_active(0)
        box.pack_start(combo, False, False, 0)
        
        param_label = Gtk.Label(label="Extra Parameters:")
        box.pack_start(param_label, False, False, 0)
        entry = Gtk.Entry()
        box.pack_start(entry, True, True, 0)
        
        run_btn = Gtk.Button(label="Run Script")
        run_btn.connect("clicked", self.on_run_selected_script, combo, entry)
        box.pack_start(run_btn, False, False, 0)
        
        return box

    def on_run_selected_script(self, button, combo, entry):
        script_path = combo.get_active_id()
        extra_params = entry.get_text().strip()
        if self.last_pixbuf is None:
            print("No capture available!")
            return
        temp_input = "last_capture.png"
        self.last_pixbuf.savev(temp_input, "png", [], [])
        cmd = ["python3", script_path, temp_input, "output.png"]
        if extra_params:
            cmd.extend(extra_params.split())
        print("Running script:", " ".join(cmd))
        subprocess.run(cmd)

    def show_keyword_dialog(self, button):
        dialog = Gtk.Dialog(title="Enter Keyword to Blur", transient_for=self, modal=True)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           "Apply", Gtk.ResponseType.APPLY,
                           "Done", Gtk.ResponseType.OK)
        content_area = dialog.get_content_area()
        entry = Gtk.Entry()
        entry.set_placeholder_text("Enter keyword (e.g. password, host, etc.)")
        content_area.add(entry)
        dialog.show_all()
        while True:
            response = dialog.run()
            if response == Gtk.ResponseType.APPLY:
                keyword = entry.get_text().strip().lower()
                if keyword:
                    self.manual_blur_by_keyword(keyword)
                    entry.set_text("")
            elif response in (Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL):
                break
        dialog.destroy()

    def manual_blur_by_keyword(self, keyword):
        # Save the current capture to a temporary file and run OCR on it.
        temp_file = "temp_capture.png"
        self.last_pixbuf.savev(temp_file, "png", [], [])
        image = cv2.imread(temp_file)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        texts = data["text"]
        lefts = data["left"]
        tops = data["top"]
        widths = data["width"]
        heights = data["height"]
        count = 0
        for i in range(len(texts)):
            if keyword in texts[i].lower():
                blur_region(image, lefts[i], tops[i], widths[i], heights[i],
                            self.manual_kernel, self.manual_sigma)
                count += 1
        print(f"Blurred {count} regions containing '{keyword}'.")
        cv2.imwrite(temp_file, image)
        self.last_pixbuf = GdkPixbuf.Pixbuf.new_from_file(temp_file)
        self.update_global_preview(self.last_pixbuf, self.last_capture_name)

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
        abs_path = os.path.abspath("screenshot.png")
        print("Screenshot saved at:", abs_path)
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
        abs_path = os.path.abspath("window_screenshot.png")
        print("Window screenshot saved at:", abs_path)
        self.update_global_preview(pb, button.get_label())
        self.show_preview_dialog(pb, title="Window Capture Preview")
        
        secrets_script = os.path.join("scripts", "secrets-handling", "main.py")
        cmd = ["python3", secrets_script, abs_path, "output.png", "51", "20"]
        print("Running secrets-handling script with command:", " ".join(cmd))
        subprocess.run(cmd)

    def on_run_script(self, button, script_name, container):
        if self.last_pixbuf is None:
            print("No capture available!")
            return
        temp_input = "last_capture.png"
        self.last_pixbuf.savev(temp_input, "png", [], [])
        params = []
        if container is not None and hasattr(container, "param_entries"):
            params = [entry.get_text() for entry in container.param_entries]
        subprocess.run(["python3", script_name, temp_input, "last_capture.png"] + params)
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
            pb = GdkPixbuf.Pixbuf.new_from_file(selected_file)
            if pb:
                self.last_pixbuf = pb
                self.last_capture_name = os.path.basename(selected_file)
                self.update_global_preview(pb, self.last_capture_name)
                abs_path = os.path.abspath(selected_file)
                secrets_script = os.path.join("scripts", "secrets-handling", "main.py")
                cmd = ["python3", secrets_script, abs_path, "output.png", "51", "20"]
                print("Running secrets-handling script with command:", " ".join(cmd))
                subprocess.run(cmd)
            else:
                print("Failed to load the selected image.")
        dialog.destroy()

if __name__ == "__main__":
    app = ScreenshotApp()
    app.connect("destroy", Gtk.main_quit)
    Gtk.main()
