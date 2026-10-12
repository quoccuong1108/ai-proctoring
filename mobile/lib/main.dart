import 'dart:async';

import 'package:flutter/material.dart';

import 'models/exam.dart';
import 'screens/exam_screen.dart';
import 'screens/splash_screen.dart';
import 'screens/student_gateway_screen.dart';
import 'services/exam_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const EduShieldApp());
}

class EduShieldApp extends StatefulWidget {
  const EduShieldApp({super.key});

  @override
  State<EduShieldApp> createState() => _EduShieldAppState();
}

class _EduShieldAppState extends State<EduShieldApp> {
  bool _isLoading = true;
  bool _examConfirmed = false;
  String _studentId = '';
  String _studentName = '';
  String _examCode = '';
  String? _errorMessage;
  Exam? _exam;
  Timer? _splashTimer;

  @override
  void initState() {
    super.initState();
    _splashTimer = Timer(const Duration(milliseconds: 1200), () {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    });
  }

  @override
  void dispose() {
    _splashTimer?.cancel();
    super.dispose();
  }

  Future<void> _continueToExam() async {
    final studentId = _studentId.trim();
    final studentName = _studentName.trim();
    final examCode = _examCode.trim();

    if (studentId.isEmpty || studentName.isEmpty || examCode.isEmpty) {
      setState(() => _errorMessage = 'Vui lòng nhập đầy đủ thông tin sinh viên và mã đề thi.');
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final fetchedExam = await ExamService.fetchExamByCode(examCode);
      setState(() {
        _exam = fetchedExam;
        _examConfirmed = true;
        _isLoading = false;
      });
    } catch (error) {
      setState(() {
        _errorMessage = error.toString().replaceFirst('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading && !_examConfirmed) {
      return const MaterialApp(
        debugShowCheckedModeBanner: false,
        home: SplashScreen(),
      );
    }

    if (_examConfirmed && _exam != null) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        home: ExamScreen(
          studentId: _studentId,
          studentName: _studentName,
          exam: _exam!,
        ),
      );
    }

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF2563EB),
        useMaterial3: true,
      ),
      home: StudentGatewayScreen(
        studentId: _studentId,
        studentName: _studentName,
        examCode: _examCode,
        onStudentIdChanged: (value) => setState(() => _studentId = value),
        onStudentNameChanged: (value) => setState(() => _studentName = value),
        onExamCodeChanged: (value) => setState(() => _examCode = value),
        isLoading: _isLoading,
        onContinue: _continueToExam,
        errorMessage: _errorMessage,
      ),
    );
  }
}
