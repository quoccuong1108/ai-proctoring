import 'package:flutter/foundation.dart';

class CameraRuntime {
  static bool get isWeb => kIsWeb;

  static String get webPermissionMessage =>
      'Camera trên web cần quyền truy cập từ trình duyệt. Hãy cho phép camera, mở ứng dụng qua http://localhost hoặc HTTPS, rồi thử lại.';

  static String get unavailableMessage =>
      'Camera không khả dụng trên môi trường hiện tại. Hãy kiểm tra quyền camera và thử lại trên thiết bị thật hoặc Android emulator.';
}
