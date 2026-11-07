// Exelixisnet IT Support: checks the panel for a newer app version and offers
// to download it. Shared by the desktop and Android home pages.
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_hbb/models/platform_model.dart';

const _kBlue = Color(0xFF0B4FA3);
bool _updateShown = false;

/// Asks the panel whether a newer version exists and, if so, shows a one-time
/// prompt with a download button. Safe to call more than once per app start.
Future<void> exelixisMaybeOfferUpdate(BuildContext context) async {
  if (_updateShown) return;
  String info = '';
  try {
    info = await bind.exelixisCheckUpdate();
  } catch (_) {
    return;
  }
  if (info.isEmpty || !context.mounted) return;
  Map<String, dynamic> m;
  try {
    m = jsonDecode(info) as Map<String, dynamic>;
  } catch (_) {
    return;
  }
  final version = (m['version'] ?? '').toString();
  final url = (m['url'] ?? '').toString();
  if (version.isEmpty || url.isEmpty) return;
  _updateShown = true;
  await showDialog(
    context: context,
    builder: (_) => _ExelixisUpdateDialog(version: version, url: url),
  );
}

class _ExelixisUpdateDialog extends StatelessWidget {
  final String version;
  final String url;
  const _ExelixisUpdateDialog({required this.version, required this.url});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Row(children: [
        Image.asset('assets/icon.png', width: 28, height: 28),
        const SizedBox(width: 10),
        const Expanded(child: Text('Νέα έκδοση · Update available')),
      ]),
      content: Text(
        'Μια νεότερη έκδοση ($version) είναι διαθέσιμη. Ενημερώστε για τις '
        'τελευταίες βελτιώσεις.\n\n'
        'A newer version ($version) is available. Update to get the latest '
        'fixes and improvements.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Αργότερα · Later'),
        ),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: _kBlue),
          onPressed: () async {
            final uri = Uri.tryParse(url);
            if (uri != null) {
              await launchUrl(uri, mode: LaunchMode.externalApplication);
            }
            if (context.mounted) Navigator.of(context).pop();
          },
          child: const Text('Λήψη · Update',
              style: TextStyle(color: Colors.white)),
        ),
      ],
    );
  }
}
