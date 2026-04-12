import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Crack3D")
    app.setOrganizationName("Crack3D")
    app.setApplicationVersion("0.1.0")
    app.setFont(QFont("Segoe UI", 9))

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
