import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/api_config.dart';

class ApiService {
  static Future<http.Response> get(String path, {Map<String, String>? queryParams}) async {
    final uri = ApiConfig.buildUri(path, queryParams: queryParams);
    return http.get(uri).timeout(const Duration(seconds: 12));
  }

  static Future<http.Response> post(
    String path, {
    Map<String, dynamic>? body,
    Map<String, String>? headers,
  }) async {
    final uri = ApiConfig.buildUri(path);
    final response = await http
        .post(
          uri,
          headers: {
            'Content-Type': 'application/json',
            ...?headers,
          },
          body: body == null ? null : jsonEncode(body),
        )
        .timeout(const Duration(seconds: 15));
    return response;
  }

  static Future<http.Response> delete(String path) async {
    final uri = ApiConfig.buildUri(path);
    return http.delete(uri).timeout(const Duration(seconds: 12));
  }
}
