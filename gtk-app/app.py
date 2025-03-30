#!/usr/bin/env python3
import gi, urllib.parse
gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, Gio, GLib, GdkPixbuf

class ScreenshotApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Wayland Screenshot App")
        self.set_default_size(800, 600)

        # Main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Create a scrolled window to host the screenshot preview
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        vbox.pack_start(scrolled, True, True, 0)

        # Image widget to display screenshot preview
        self.preview = Gtk.Image()
        scrolled.add(self.preview)

        # Button to capture a screenshot via Wayland portal
        capture_button = Gtk.Button(label="Capture Screenshot (Wayland)")
        capture_button.connect("clicked", self.on_capture_clicked)
        vbox.pack_start(capture_button, False, False, 0)

        self.show_all()

    def on_capture_clicked(self, button):
        # Get a connection to the session bus
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # Create a DBus proxy for the xdg-desktop-portal screenshot interface
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            None,
        )
        # Options dictionary (empty for now; you can add keys if needed)
        options = GLib.Variant('a{sv}', {})
        # Use an arbitrary handle token
        handle_token = "screenshot_token"
        # Call the Screenshot.TakeScreenshot method synchronously.
        # The method signature expects a tuple: (handle_token, options)
        try:
            result_variant = proxy.call_sync(
                "Screenshot.TakeScreenshot",
                GLib.Variant('(sa{sv})', (handle_token, options)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except GLib.Error as e:
            print("DBus call failed:", e)
            return

        # The method returns a tuple: (result, result_dict)
        # where result_dict should contain a key "uri"
        status, result_dict = result_variant.unpack()
        screenshot_uri = result_dict.get("uri")
        if not screenshot_uri:
            print("No screenshot URI returned. Status:", status)
            return

        # Convert file:// URI to file path
        if screenshot_uri.startswith("file://"):
            file_path = urllib.parse.unquote(screenshot_uri[len("file://"):])
        else:
            file_path = screenshot_uri

        # Load the screenshot file into a GdkPixbuf
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file(file_path)
        except Exception as e:
            print("Failed to load screenshot file:", e)
            return

        # Optionally, scale the pixbuf to create a preview (e.g., 480px wide, preserving aspect ratio)
        new_width = 480
        scale_factor = new_width / float(pb.get_width())
        new_height = int(pb.get_height() * scale_factor)
        scaled_pb = pb.scale_simple(new_width, new_height, GdkPixbuf.InterpType.BILINEAR)
        self.preview.set_from_pixbuf(scaled_pb)

if __name__ == "__main__":
    app = ScreenshotApp()
    app.connect("destroy", Gtk.main_quit)
    Gtk.main()

