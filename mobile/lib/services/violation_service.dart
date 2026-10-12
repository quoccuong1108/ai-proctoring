import 'dart:convert';

import '../models/violation.dart';
import 'api_service.dart';

class ViolationService {
  static Future<void> reportViolation(ViolationRecord record) async {
    final response = await ApiService.post(
      '/api/violations',
      body: record.toJson(),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final body = response.body;
      throw Exception(body.isNotEmpty ? body : 'Không thể gửi vi phạm');
    }
  }

  static String encodeImageToBase64(List<int> imageBytes) {
    return base64Encode(imageBytes);
  }
}
