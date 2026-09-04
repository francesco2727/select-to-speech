#ifndef RUNNER_WIN32_WINDOW_H_
#define RUNNER_WIN32_WINDOW_H_

#include <windows.h>

#include <functional>
#include <memory>
#include <string>

// A class that abstracts the creation and management of a Win32 window.
class Win32Window {
 public:
  struct Point {
    unsigned int x;
    unsigned int y;
    Point(unsigned int x, unsigned int y) : x(x), y(y) {}
  };

  struct Size {
    unsigned int width;
    unsigned int height;
    Size(unsigned int width, unsigned int height)
        : width(width), height(height) {}
  };

  Win32Window();
  virtual ~Win32Window();

  // Creates and shows a win32 window with |title| and position and size using
  // |origin| and |size|. New windows are created visible by default. Returns
  // true if window creation was successful.
  bool Create(const std::wstring& title, const Point& origin, const Size& size);

  // Shows the window.
  bool Show();

  // Hides the window.
  bool Hide();

  // Releases OS resources associated with window. |child_content_initialized_|
  // must be reset prior to calling this method.
  void Destroy();

  // Inserts |content| into the window tree.
  void SetChildContent(HWND content);

  // Returns the backing Window handle to enable clients to set capture and
  // other window attributes.
  HWND GetHandle();

  // If true, closing this window doesn't destroy the window, but hides it.
  void SetQuitOnClose(bool quit_on_close);

  // Returns the client area rectangle for the window.
  RECT GetClientArea();

 protected:
  // Processes and acts on any OS messages sent to the window.
  // Method is overridable to allow subclasses to extend functionality.
  virtual LRESULT MessageHandler(HWND window,
                                 UINT const message,
                                 WPARAM const wparam,
                                 LPARAM const lparam) noexcept;

  // Called when Create is called. Subclasses should override this method to
  // perform any setup requires child content. |content| is the HWND of the
  // window that will be child of this window.
  virtual bool OnCreate();

  // Called when Destroy is called. Subclasses should override this method to
  // perform any cleanup.
  virtual void OnDestroy();

 private:
  friend class WindowClassRegistrar;

  // OS callback called by message pump. Handles the WM_NCCREATE message which
  // is passed when the window is first created. Overrides various status
  // values for window directed.
  static LRESULT CALLBACK WndProc(HWND const window,
                                  UINT const message,
                                  WPARAM const wparam,
                                  LPARAM const lparam) noexcept;

  // Retrieves a class instance pointer for |window|
  static Win32Window* GetThisFromHandle(HWND const window) noexcept;

  bool quit_on_close_ = true;

  // window handle for top level window.
  HWND window_handle_ = nullptr;

  // window handle for hosted content.
  HWND child_content_ = nullptr;
};

#endif  // RUNNER_WIN32_WINDOW_H_
