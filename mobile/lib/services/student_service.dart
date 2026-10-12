import 'dart:convert';

import '../models/student.dart';
import 'api_service.dart';

class StudentService {
  static Future<StudentProfile> fetchStudentProfile({required String studentId, required String studentName}) async {
    final response = await ApiService.get('/health');
    if (response.statusCode != 200) {
      throw Exception('Backend unavailable');
    }

    return StudentProfile(
      studentId: studentId.trim(),
      name: studentName.trim(),
    );
  }

  static String buildViolationSnapshotDataUrl(List<int> bytes) {
    return 'data:image/jpeg;base64,${base64Encode(bytes)}';
  }
}
