import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ui/main.dart';

void main() {
  testWidgets('ShortcutRecorderWidget displays M3 keycaps and records key press', (WidgetTester tester) async {
    String? recordedKey;

    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(useMaterial3: true, colorSchemeSeed: kDefaultSeedColor),
        home: Scaffold(
          body: ShortcutRecorderWidget(
            label: 'Trigger Key',
            modifierKey: 'alt',
            initialValue: 'esc',
            promptText: 'Press a key...',
            onChanged: (val) => recordedKey = val,
          ),
        ),
      ),
    );

    expect(find.text('ALT'), findsOneWidget);
    expect(find.text('ESC'), findsOneWidget);

    await tester.tap(find.byType(ShortcutRecorderWidget));
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.text('Press a key...'), findsOneWidget);

    await tester.sendKeyDownEvent(LogicalKeyboardKey.keyK);
    await tester.pump();
    expect(recordedKey, equals('k'));
  });
}
