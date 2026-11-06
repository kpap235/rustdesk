// Exelixisnet IT Support: the name window shown once after installation, and
// the support contact line on the home page.
import 'package:flutter/material.dart';
import 'package:flutter_hbb/models/platform_model.dart';

const kExelixisPhone = '2615 00 2000';
const kExelixisEmail = 'info@exelixisnet.gr';
const _kBlue = Color(0xFF0B4FA3);
const _kRed = Color(0xFFC21F3A);

bool _exelixisDialogShown = false;

String _exelixisVersion() {
  try {
    return bind.exelixisVersion();
  } catch (_) {
    return '';
  }
}

/// Shows the name window if this installed copy has not registered yet.
/// Safe to call repeatedly: it opens at most once per app start.
Future<void> exelixisMaybeAskName(BuildContext context) async {
  if (_exelixisDialogShown) return;
  bool needed = false;
  try {
    needed = bind.exelixisNeedsRegistration();
  } catch (_) {}
  if (!needed || !context.mounted) return;
  _exelixisDialogShown = true;
  await showDialog(
    context: context,
    barrierDismissible: false,
    builder: (_) => const _ExelixisRegisterDialog(),
  );
}

class _ExelixisRegisterDialog extends StatefulWidget {
  const _ExelixisRegisterDialog();

  @override
  State<_ExelixisRegisterDialog> createState() => _ExelixisRegisterDialogState();
}

class _ExelixisRegisterDialogState extends State<_ExelixisRegisterDialog> {
  final _name = TextEditingController();
  final _phone = TextEditingController();
  bool _busy = false;
  String _message = '';
  bool _done = false;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _message = 'Please enter your name or company name.');
      return;
    }
    setState(() {
      _busy = true;
      _message = '';
    });
    final result = await bind.exelixisRegister(
        name: _name.text.trim(), phone: _phone.text.trim());
    if (!mounted) return;
    setState(() {
      _busy = false;
      _done = true;
      _message = result.isEmpty
          ? 'Thank you! Exelixisnet can now help you remotely.'
          : result;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Row(children: [
        Image.asset('assets/icon.png', width: 32, height: 32),
        const SizedBox(width: 12),
        const Expanded(child: Text('Welcome to Exelixisnet IT Support')),
      ]),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'So that our technicians know who you are, please enter your '
              'name or company name.',
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _name,
              autofocus: true,
              enabled: !_busy && !_done,
              maxLength: 120,
              decoration: const InputDecoration(
                labelText: 'Full name or company name *',
                counterText: '',
              ),
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _phone,
              enabled: !_busy && !_done,
              maxLength: 40,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                labelText: 'Phone (optional)',
                counterText: '',
              ),
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: 14),
            Text(
              'By pressing OK you allow Exelixisnet technicians to connect to '
              'this computer for support. You can uninstall the app at any '
              'time to stop this.',
              style: TextStyle(
                  fontSize: 12, color: Theme.of(context).hintColor),
            ),
            if (_message.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(_message,
                  style: TextStyle(
                      color: _done && !_message.startsWith('Could')
                          ? Colors.green[700]
                          : _kRed)),
            ],
          ],
        ),
      ),
      actions: _done
          ? [
              ElevatedButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Close'),
              )
            ]
          : [
              TextButton(
                onPressed: _busy ? null : () => Navigator.of(context).pop(),
                child: const Text('Later'),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _kBlue),
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('OK', style: TextStyle(color: Colors.white)),
              ),
            ],
    );
  }
}

/// Support contact shown under the logo on the home page.
Widget exelixisSupportContact(BuildContext context) {
  final style = TextStyle(fontSize: 12, color: Theme.of(context).hintColor);
  return Padding(
    padding: const EdgeInsets.only(left: 12, right: 12, top: 6),
    child: Column(children: [
      Text('IT Support', style: style.copyWith(fontWeight: FontWeight.w600)),
      SelectableText('$kExelixisPhone  ·  $kExelixisEmail', style: style),
      Text('Version ${_exelixisVersion()}',
          style: style.copyWith(fontSize: 11)),
    ]),
  );
}
