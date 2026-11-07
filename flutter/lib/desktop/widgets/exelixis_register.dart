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

/// A "? Instructions / Οδηγίες" link for the QuickSupport home page.
Widget exelixisInstructionsButton(BuildContext context) {
  return TextButton.icon(
    icon: const Icon(Icons.help_outline, size: 18, color: _kBlue),
    label: const Text('Οδηγίες · Instructions',
        style: TextStyle(fontSize: 12, color: _kBlue)),
    onPressed: () => showDialog(
      context: context,
      builder: (_) => const _ExelixisInstructionsDialog(),
    ),
  );
}

class _ExelixisInstructionsDialog extends StatelessWidget {
  const _ExelixisInstructionsDialog();

  @override
  Widget build(BuildContext context) {
    final hint = TextStyle(color: Theme.of(context).hintColor, fontSize: 13);
    return AlertDialog(
      title: Row(children: [
        Image.asset('assets/icon.png', width: 28, height: 28),
        const SizedBox(width: 10),
        const Expanded(child: Text('Πώς λειτουργεί · How it works')),
      ]),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _section(
                'Ελληνικά',
                const [
                  'Για να σας βοηθήσουμε, τηλεφωνήστε μας στο $kExelixisPhone και '
                      'διαβάστε μας τον κωδικό μίας χρήσης που εμφανίζεται σε αυτό '
                      'το παράθυρο. Αν αλλάξει, πατήστε το κουμπί ανανέωσης δίπλα του.',
                  'Όταν συνδεόμαστε, βλέπουμε την οθόνη σας και μπορούμε να '
                      'χειριστούμε τον υπολογιστή για να λύσουμε το πρόβλημα. '
                      'Βλέπετε ό,τι κάνουμε σε όλη τη διάρκεια.',
                  'Το κουμπί «Εγκατάσταση» αφήνει το πρόγραμμα μόνιμα, ώστε να '
                      'μπορούμε να συνδεθούμε και χωρίς να τρέχετε κάθε φορά το αρχείο. '
                      'Ξεκινά αυτόματα με τον υπολογιστή.',
                  'Ιδιωτικότητα: συνδεόμαστε μόνο όταν μας το ζητήσετε. Μπορείτε να '
                      'κλείσετε το πρόγραμμα ή να το απεγκαταστήσετε όποτε θέλετε για '
                      'να σταματήσει κάθε πρόσβαση.',
                ],
                hint,
              ),
              const SizedBox(height: 16),
              _section(
                'English',
                const [
                  'To get help, call us on $kExelixisPhone and read out the '
                      'one-time code shown in this window. If it changes, press the '
                      'refresh button next to it.',
                  'When we connect we can see your screen and control the computer '
                      'to fix the problem. You can watch everything we do.',
                  'The "Install" button keeps the program on the computer so we can '
                      'connect without you running the file each time. It starts '
                      'automatically with the computer.',
                  'Privacy: we connect only when you ask us to. You can close the '
                      'program or uninstall it at any time to stop all access.',
                ],
                hint,
              ),
            ],
          ),
        ),
      ),
      actions: [
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: _kBlue),
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('OK', style: TextStyle(color: Colors.white)),
        ),
      ],
    );
  }

  Widget _section(String title, List<String> points, TextStyle hint) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title,
            style: const TextStyle(
                fontWeight: FontWeight.w700, color: _kRed, fontSize: 14)),
        const SizedBox(height: 6),
        for (final p in points)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('•  ', style: TextStyle(color: _kBlue)),
              Expanded(child: Text(p, style: hint)),
            ]),
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
    child: Column(crossAxisAlignment: CrossAxisAlignment.center, children: [
      Text('IT Support',
          textAlign: TextAlign.center,
          style: style.copyWith(fontWeight: FontWeight.w600)),
      SelectableText('$kExelixisPhone  ·  $kExelixisEmail',
          textAlign: TextAlign.center, style: style),
      Text('Version ${_exelixisVersion()}',
          textAlign: TextAlign.center, style: style.copyWith(fontSize: 11)),
    ]),
  );
}
