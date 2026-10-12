// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/config/api_config.dart';
import 'package:mobile/main.dart';
import 'package:mobile/utils/camera_runtime.dart';

void main() {
  testWidgets('app boots to splash screen', (WidgetTester tester) async {
    await tester.pumpWidget(const EduShieldApp());

    expect(find.text('EduShield AI'), findsOneWidget);
    expect(find.text('AI Proctoring for online exams'), findsOneWidget);
  });

  test('web camera guidance explains browser permission requirement', () {
    final message = CameraRuntime.webPermissionMessage;

    expect(message, contains('trình duyệt'));
    expect(message, contains('camera'));
  });

  test('backend url prefers explicit public host and https for ngrok-style domains', () {
    expect(
      ApiConfig.resolveBaseUrl(hostOverride: 'https://think-uploader-drippy.ngrok-free.dev'),
      'https://think-uploader-drippy.ngrok-free.dev',
    );

    expect(
      ApiConfig.resolveBaseUrl(hostOverride: 'think-uploader-drippy.ngrok-free.dev'),
      'https://think-uploader-drippy.ngrok-free.dev',
    );

    expect(
      ApiConfig.resolveBaseUrl(hostOverride: 'localhost'),
      'http://localhost:8000',
    );
  });
}
