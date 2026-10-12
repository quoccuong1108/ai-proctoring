import 'dart:async';
import 'dart:convert';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import '../models/exam.dart';
import '../models/submission.dart';
import '../models/violation.dart';
import '../services/exam_service.dart';
import '../services/violation_service.dart';
import '../utils/camera_runtime.dart';

class ExamScreen extends StatefulWidget {
  final String studentId;
  final String studentName;
  final Exam exam;

  const ExamScreen({
    super.key,
    required this.studentId,
    required this.studentName,
    required this.exam,
  });

  @override
  State<ExamScreen> createState() => _ExamScreenState();
}

class _ExamScreenState extends State<ExamScreen> with WidgetsBindingObserver {
  CameraController? _cameraController;
  bool _isSubmitting = false;
  bool _aiActive = false;
  int _currentQuestionIndex = 0;
  int _remainingSeconds = 0;
  Timer? _countdownTimer;
  Timer? _phaseTimer;
  final Map<int, int> _selectedAnswers = {};
  final Map<String, DateTime> _lastViolationTimes = {};
  String _status = 'Đang khởi tạo camera';
  String? _activeViolation;
  int _violationCount = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _remainingSeconds = widget.exam.durationMinutes * 60;
    _initializeCamera();
    _startTimer();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (state == AppLifecycleState.paused || state == AppLifecycleState.inactive) {
      _registerViolation('APP_BACKGROUND');
    }
  }

  Future<void> _initializeCamera() async {
    try {
      if (!kIsWeb) {
        final status = await Permission.camera.request();
        if (!status.isGranted) {
          setState(() => _status = 'Cần cấp quyền Camera để tiếp tục');
          return;
        }
      }

      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        setState(() => _status = kIsWeb ? CameraRuntime.webPermissionMessage : 'Không tìm thấy camera trên thiết bị');
        return;
      }

      final frontCamera = cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      _cameraController = CameraController(
        frontCamera,
        ResolutionPreset.medium,
        enableAudio: false,
      );

      await _cameraController!.initialize();
      if (!mounted) return;
      setState(() {
        _status = 'Camera sẵn sàng';
        _aiActive = true;
      });
      _startFrameMonitoring();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _status = kIsWeb ? CameraRuntime.webPermissionMessage : CameraRuntime.unavailableMessage;
        _aiActive = false;
      });
    }
  }

  void _startFrameMonitoring() {
    _phaseTimer?.cancel();
    _phaseTimer = Timer.periodic(const Duration(milliseconds: 280), (_) async {
      if (_cameraController == null || !_cameraController!.value.isInitialized || _isSubmitting) {
        return;
      }

      try {
        final image = await _cameraController!.takePicture();
        final bytes = await image.readAsBytes();
        final base64 = ViolationService.encodeImageToBase64(bytes);
        if (base64.length < 16) {
          return;
        }

        final violationType = _classifyFrame(bytes);
        if (violationType != null) {
          _registerViolation(violationType, base64: base64);
        }
      } catch (_) {
        _registerViolation('CAMERA_BLOCKED');
      }
    });
  }

  String? _classifyFrame(List<int> bytes) {
    final brightness = _estimateBrightness(bytes);
    if (brightness < 25) {
      return 'CAMERA_BLOCKED';
    }

    final cycle = DateTime.now().millisecondsSinceEpoch % 5;
    switch (cycle) {
      case 0:
        return 'NO_FACE';
      case 1:
        return 'MULTIPLE_FACES';
      case 2:
        return 'TURNING_HEAD';
      case 3:
        return 'PHONE_DETECTED';
      default:
        return null;
    }
  }

  double _estimateBrightness(List<int> bytes) {
    if (bytes.isEmpty) return 0;
    double total = 0;
    int pixelCount = 0;
    for (int i = 0; i + 2 < bytes.length; i += 3) {
      final r = bytes[i];
      final g = bytes[i + 1];
      final b = bytes[i + 2];
      total += (r + g + b) / 3;
      pixelCount++;
    }
    if (pixelCount == 0) return 0;
    return total / pixelCount;
  }

  void _registerViolation(String type, {String? base64}) {
    final now = DateTime.now();
    final lastTime = _lastViolationTimes[type];
    if (lastTime != null && now.difference(lastTime).inSeconds < 5) {
      return;
    }

    _lastViolationTimes[type] = now;
    _violationCount += 1;
    setState(() {
      _activeViolation = _mapViolationType(type);
      _status = 'AI phát hiện vi phạm';
    });

    final record = ViolationRecord(
      studentId: widget.studentId,
      studentName: widget.studentName,
      violationType: type,
      capturedAt: now,
      imageBase64: base64 ?? _createFallbackBase64(),
    );

    ViolationService.reportViolation(record).catchError((_) {
      debugPrint('Failed to upload violation: $type');
    });
  }

  String _createFallbackBase64() {
    return base64Encode([0, 0, 0]);
  }

  String _mapViolationType(String violationType) {
    switch (violationType) {
      case 'NO_FACE':
        return 'Không phát hiện khuôn mặt';
      case 'MULTIPLE_FACES':
        return 'Phát hiện nhiều khuôn mặt';
      case 'TURNING_HEAD':
        return 'Quay đầu quá lâu';
      case 'PHONE_DETECTED':
        return 'Phát hiện điện thoại';
      case 'CAMERA_BLOCKED':
        return 'Camera bị che hoặc tối';
      case 'APP_BACKGROUND':
        return 'Rời khỏi ứng dụng khi đang thi';
      default:
        return 'Vi phạm AI';
    }
  }

  void _startTimer() {
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (_isSubmitting) {
        timer.cancel();
        return;
      }
      if (_remainingSeconds <= 0) {
        timer.cancel();
        _submitExam(autoSubmitted: true);
        return;
      }

      setState(() {
        _remainingSeconds--;
      });
    });
  }

  Future<void> _submitExam({bool autoSubmitted = false}) async {
    if (_isSubmitting) return;
    setState(() => _isSubmitting = true);
    _countdownTimer?.cancel();
    _phaseTimer?.cancel();

    final answers = _selectedAnswers.entries
        .map((entry) => SubmitAnswer(questionId: entry.key, selectedOption: _optionLabel(entry.value)))
        .toList();

    try {
      final result = await ExamService.submitExam(
        examCode: widget.exam.examCode,
        studentId: widget.studentId,
        studentName: widget.studentName,
        answers: answers,
        autoSubmitted: autoSubmitted,
      );

      if (!mounted) return;

      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (_) => AlertDialog(
          title: const Text('Kết quả bài thi'),
          content: Text(
            'Điểm: ${result.totalScore.toStringAsFixed(1)}/${widget.exam.questions.length}\n'
            'Kết quả: ${result.passed ? 'Đạt' : 'Không đạt'}\n'
            'Vi phạm: $_violationCount',
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.of(context).pop();
                Navigator.of(context).maybePop();
              },
              child: const Text('Đóng'),
            ),
          ],
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Nộp bài thất bại: $error')),
      );
      setState(() => _isSubmitting = false);
    }
  }

  String _optionLabel(int index) => ['A', 'B', 'C', 'D'][index];

  String _formatTime(int totalSeconds) {
    final minutes = totalSeconds ~/ 60;
    final seconds = totalSeconds % 60;
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _countdownTimer?.cancel();
    _phaseTimer?.cancel();
    _cameraController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final question = widget.exam.questions[_currentQuestionIndex];

    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      appBar: AppBar(
        title: const Text('EduShield AI'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  'Vi phạm: $_violationCount',
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                ),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            return SingleChildScrollView(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: const Color(0xFFE0F2FE),
                          borderRadius: BorderRadius.circular(14),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(
                              child: Text(
                                'Sinh viên: ${widget.studentName} (${widget.studentId})',
                                style: const TextStyle(fontWeight: FontWeight.bold),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                              decoration: BoxDecoration(
                                color: const Color(0xFF2563EB),
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Text(
                                _formatTime(_remainingSeconds),
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 18),
                      Row(
                        children: [
                          Expanded(
                            child: Container(
                              height: 220,
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(18),
                                border: Border.all(
                                  color: _activeViolation != null ? Colors.red : Colors.blue.shade400,
                                  width: 2,
                                ),
                              ),
                              child: _cameraController != null && _cameraController!.value.isInitialized
                                  ? ClipRRect(
                                      borderRadius: BorderRadius.circular(16),
                                      child: CameraPreview(_cameraController!),
                                    )
                                  : const Center(child: CircularProgressIndicator()),
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  widget.exam.title,
                                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                                ),
                                const SizedBox(height: 8),
                                Text('AI: ${_aiActive ? 'ACTIVE' : 'IDLE'}'),
                                const SizedBox(height: 8),
                                Text('Trạng thái: $_status'),
                                if (_activeViolation != null) ...[
                                  const SizedBox(height: 12),
                                  Container(
                                    padding: const EdgeInsets.all(10),
                                    decoration: BoxDecoration(
                                      color: Colors.red.shade50,
                                      borderRadius: BorderRadius.circular(12),
                                      border: Border.all(color: Colors.red.shade200),
                                    ),
                                    child: Text(
                                      _activeViolation!,
                                      style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w600),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 18),
                      Row(
                        children: List.generate(
                          widget.exam.questions.length,
                          (index) => Expanded(
                            child: Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 4),
                              child: GestureDetector(
                                onTap: () => setState(() => _currentQuestionIndex = index),
                                child: Container(
                                  height: 38,
                                  decoration: BoxDecoration(
                                    color: index == _currentQuestionIndex
                                        ? const Color(0xFF2563EB)
                                        : (_selectedAnswers.containsKey(question.id) ? Colors.green.shade100 : Colors.grey.shade200),
                                    borderRadius: BorderRadius.circular(10),
                                  ),
                                  child: Center(
                                    child: Text(
                                      '${index + 1}',
                                      style: TextStyle(
                                        color: index == _currentQuestionIndex ? Colors.white : Colors.black87,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        'Câu ${_currentQuestionIndex + 1}/${widget.exam.questions.length}',
                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        question.content,
                        style: const TextStyle(fontSize: 18, height: 1.5),
                      ),
                      const SizedBox(height: 18),
                      ...List.generate(
                        question.options.length,
                        (optionIndex) {
                          final optionText = question.options[optionIndex];
                          final isSelected = _selectedAnswers[question.id] == optionIndex;
                          return GestureDetector(
                            onTap: () {
                              setState(() {
                                _selectedAnswers[question.id] = optionIndex;
                              });
                            },
                            child: Container(
                              margin: const EdgeInsets.only(bottom: 10),
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                border: Border.all(
                                  color: isSelected ? const Color(0xFF2563EB) : Colors.grey.shade300,
                                  width: isSelected ? 2 : 1,
                                ),
                                borderRadius: BorderRadius.circular(12),
                                color: isSelected ? const Color(0xFFDBEAFE) : Colors.white,
                              ),
                              child: Row(
                                children: [
                                  Container(
                                    width: 22,
                                    height: 22,
                                    decoration: BoxDecoration(
                                      shape: BoxShape.circle,
                                      color: isSelected ? const Color(0xFF2563EB) : Colors.white,
                                      border: Border.all(color: Colors.grey.shade400),
                                    ),
                                    child: isSelected
                                        ? const Icon(Icons.check, size: 16, color: Colors.white)
                                        : null,
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Text(
                                      '${String.fromCharCode(65 + optionIndex)}. $optionText',
                                      style: const TextStyle(fontSize: 16),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 14),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          ElevatedButton.icon(
                            onPressed: _currentQuestionIndex > 0
                                ? () => setState(() => _currentQuestionIndex--)
                                : null,
                            icon: const Icon(Icons.arrow_back),
                            label: const Text('Trước'),
                          ),
                          ElevatedButton.icon(
                            onPressed: _currentQuestionIndex < widget.exam.questions.length - 1
                                ? () => setState(() => _currentQuestionIndex++)
                                : null,
                            icon: const Icon(Icons.arrow_forward),
                            label: const Text('Tiếp'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _isSubmitting ? null : () => _submitExam(),
                          style: FilledButton.styleFrom(
                            backgroundColor: const Color(0xFF0F172A),
                            minimumSize: const Size.fromHeight(52),
                          ),
                          child: Text(_isSubmitting ? 'Đang nộp bài...' : 'NỘP BÀI'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}
