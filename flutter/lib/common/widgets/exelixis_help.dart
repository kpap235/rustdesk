// Exelixisnet IT Support: the customer's "Call for help" button, which raises a
// support request on the panel so a technician sees it and connects.
import 'package:flutter/material.dart';
import 'package:flutter_hbb/models/platform_model.dart';

const _kRed = Color(0xFFC21F3A);

/// A prominent "Call for help" button for the QuickSupport home screens.
Widget exelixisHelpButton(BuildContext context, {bool wide = false}) {
  final btn = ElevatedButton.icon(
    icon: const Icon(Icons.support_agent, color: Colors.white),
    label: const FittedBox(
      fit: BoxFit.scaleDown,
      child: Text('Κλήση για βοήθεια · Help',
          maxLines: 1,
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
    ),
    style: ElevatedButton.styleFrom(
      backgroundColor: _kRed,
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    onPressed: () => _showHelpDialog(context),
  );
  return wide ? SizedBox(width: double.infinity, child: btn) : btn;
}

Future<void> _showHelpDialog(BuildContext context) async {
  await showDialog(context: context, builder: (_) => const _HelpDialog());
}

class _HelpDialog extends StatefulWidget {
  const _HelpDialog();
  @override
  State<_HelpDialog> createState() => _HelpDialogState();
}

class _HelpDialogState extends State<_HelpDialog> {
  final _msg = TextEditingController();
  bool _busy = false;
  bool _done = false;
  String _message = '';

  @override
  void dispose() {
    _msg.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    setState(() {
      _busy = true;
      _message = '';
    });
    String result;
    try {
      result = await bind.exelixisCallForHelp(message: _msg.text.trim());
    } catch (_) {
      result = 'Could not reach the support server.';
    }
    if (!mounted) return;
    setState(() {
      _busy = false;
      _done = result.isEmpty;
      _message = result.isEmpty
          ? 'Το αίτημά σας στάλθηκε. Ένας τεχνικός θα συνδεθεί σύντομα.\n'
              'Your request was sent. A technician will connect shortly.'
          : result;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Row(children: [
        Image.asset('assets/icon.png', width: 28, height: 28),
        const SizedBox(width: 10),
        const Expanded(child: Text('Κλήση για βοήθεια · Call for help')),
      ]),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!_done) ...[
              const Text(
                'Πείτε μας με δυο λόγια το πρόβλημα (προαιρετικά) και πατήστε '
                'αποστολή.\nTell us briefly what the problem is (optional), then send.',
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _msg,
                enabled: !_busy,
                maxLength: 200,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Πρόβλημα · Problem (optional)',
                  counterText: '',
                ),
              ),
            ],
            if (_message.isNotEmpty)
              Text(_message,
                  style: TextStyle(
                      color: _done ? Colors.green[700] : _kRed)),
          ],
        ),
      ),
      actions: _done
          ? [
              ElevatedButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('OK'),
              )
            ]
          : [
              TextButton(
                onPressed: _busy ? null : () => Navigator.of(context).pop(),
                child: const Text('Άκυρο · Cancel'),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _kRed),
                onPressed: _busy ? null : _send,
                child: _busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('Αποστολή · Send',
                        style: TextStyle(color: Colors.white)),
              ),
            ],
    );
  }
}
