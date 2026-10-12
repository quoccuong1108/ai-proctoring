import 'dart:convert';

import '../models/exam.dart';
import '../models/submission.dart';
import 'api_service.dart';

class ExamService {
  static Future<Exam> fetchExamByCode(String examCode) async {
    final response = await ApiService.get('/api/exams/code/$examCode/take');
    if (response.statusCode != 200) {
      final message = response.body.isNotEmpty ? response.body : 'Không thể tải đề thi';
      throw Exception(message);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return Exam.fromJson(data);
  }

  static Future<ExamResult> submitExam({
    required String examCode,
    required String studentId,
    required String studentName,
    required List<SubmitAnswer> answers,
    required bool autoSubmitted,
  }) async {
    final request = SubmitExamRequest(
      studentId: studentId,
      studentName: studentName,
      answers: answers,
      autoSubmitted: autoSubmitted,
    );

    final response = await ApiService.post(
      '/api/exams/code/$examCode/submit',
      body: request.toJson(),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final body = response.body;
      throw Exception(body.isNotEmpty ? body : 'Nộp bài thất bại');
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return ExamResult.fromJson(data);
  }
}
