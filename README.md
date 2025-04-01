# SmartScreenShot
A gtk based application that takes screenshot and modifies it by blurring sensitive data
# Workflow
- The application takes a screenshot , and sends it to a script that runs an ml model that scans it for sensitive information
- The sensitive information is higlighted and is blurred

# Install
sudo dnf install python3-gobject gtk3 libwnck gdk-pixbuf2