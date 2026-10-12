import 'package:flutter/foundation.dart';

class ApiConfig {
  static const String backendHostOverride = String.fromEnvironment(
    'BACKEND_HOST',
    defaultValue: '10.0.2.2',
  );

  static const int backendPort = 8000;

  static String _trimTrailingSlash(String value) {
    return value.endsWith('/') ? value.substring(0, value.length - 1) : value;
  }

  static String resolveBaseUrl({String? hostOverride}) {
    final override = (hostOverride ?? backendHostOverride).trim();

    if (override.isNotEmpty) {
      if (override.startsWith('http://') || override.startsWith('https://')) {
        return _trimTrailingSlash(override);
      }

      if (override == 'localhost' || override == '127.0.0.1' || override == '0.0.0.0') {
        return 'http://$override:$backendPort';
      }

      if (override == '10.0.2.2') {
        return 'http://$override:$backendPort';
      }

      if (override.contains(':')) {
        return 'https://$override';
      }

      return 'https://$override';
    }

    if (!kIsWeb) {
      return 'http://$backendHostOverride:$backendPort';
    }

    final browserHost = Uri.base.host;
    if (browserHost.isNotEmpty &&
        browserHost != 'localhost' &&
        browserHost != '127.0.0.1' &&
        browserHost != '0.0.0.0') {
      final scheme = Uri.base.scheme == 'https' ? 'https' : 'http';
      return scheme == 'https' ? 'https://$browserHost' : 'http://$browserHost:$backendPort';
    }

    final fallbackHost = backendHostOverride == '10.0.2.2' ? 'localhost' : backendHostOverride;
    return 'http://$fallbackHost:$backendPort';
  }

  static String get baseUrl => resolveBaseUrl();

  static Uri buildUri(String path, {Map<String, String>? queryParams, String? hostOverride}) {
    final safePath = path.startsWith('/') ? path : '/$path';
    final uri = Uri.parse('${resolveBaseUrl(hostOverride: hostOverride)}$safePath');
    if (queryParams == null || queryParams.isEmpty) {
      return uri;
    }
    return uri.replace(queryParameters: queryParams);
  }
}
