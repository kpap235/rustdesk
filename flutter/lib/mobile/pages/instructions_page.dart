// Exelixisnet IT Support: the QuickSupport guidance tab for Android customers.
// It explains, in Greek and English, what to allow so a technician can connect,
// and shows a live checklist with a green tick for each permission granted.
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../common.dart';
import '../../consts.dart';
import '../../models/server_model.dart';
import 'home_page.dart';

const _kBlue = Color(0xFF0B4FA3);
const _kRed = Color(0xFFC21F3A);

class InstructionsPage extends StatefulWidget implements PageShape {
  InstructionsPage({Key? key}) : super(key: key);

  @override
  final title = 'Οδηγίες · Guide';

  @override
  final icon = const Icon(Icons.help_outline);

  @override
  final appBarActions = <Widget>[];

  @override
  State<InstructionsPage> createState() => _InstructionsPageState();
}

class _InstructionsPageState extends State<InstructionsPage>
    with WidgetsBindingObserver {
  bool _notificationOk = false;
  bool _overlayOk = false;
  bool _batteryOk = false;
  bool _startOnBootOk = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refresh();
    }
  }

  Future<void> _refresh() async {
    final notification =
        await AndroidPermissionManager.check(kAndroid13Notification);
    final overlay = await AndroidPermissionManager.check(kSystemAlertWindow);
    final battery = await AndroidPermissionManager.check(
        kRequestIgnoreBatteryOptimizations);
    bool startOnBoot = false;
    try {
      startOnBoot = await gFFI.invokeMethod(AndroidChannel.kGetStartOnBootOpt);
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _notificationOk = notification;
      _overlayOk = overlay;
      _batteryOk = battery;
      _startOnBootOk = startOnBoot && overlay && battery;
    });
  }

  Future<void> _requestOverlay() async {
    await AndroidPermissionManager.request(kSystemAlertWindow);
    await _refresh();
  }

  Future<void> _requestBattery() async {
    await AndroidPermissionManager.request(kRequestIgnoreBatteryOptimizations);
    await _refresh();
  }

  Future<void> _enableStartOnBoot() async {
    if (!_overlayOk) {
      await _requestOverlay();
    }
    if (!_batteryOk) {
      await _requestBattery();
    }
    if (_overlayOk && _batteryOk) {
      await gFFI.invokeMethod(AndroidChannel.kSetStartOnBootOpt, true);
    }
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: gFFI.serverModel,
      child: Consumer<ServerModel>(
        builder: (context, serverModel, child) => _body(context, serverModel),
      ),
    );
  }

  Widget _body(BuildContext context, ServerModel serverModel) {
    final hint = TextStyle(color: Theme.of(context).hintColor, fontSize: 13);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Image.asset('assets/icon.png', width: 36, height: 36),
            const SizedBox(width: 12),
            Expanded(
              child: Text('Exelixisnet IT Support',
                  style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: Theme.of(context).textTheme.titleLarge?.color)),
            ),
          ]),
          const SizedBox(height: 14),
          _intro(hint),
          const SizedBox(height: 18),
          Text('Βήματα · Checklist',
              style: const TextStyle(
                  fontWeight: FontWeight.w700, color: _kRed, fontSize: 15)),
          const SizedBox(height: 4),
          _CheckRow(
            'Κοινή χρήση οθόνης · Screen sharing',
            serverModel.mediaOk,
            () => serverModel.toggleService(),
          ),
          _CheckRow(
            'Χειρισμός συσκευής · Control (accessibility)',
            serverModel.inputOk,
            () => serverModel.toggleInput(),
          ),
          _CheckRow(
            'Πρόσβαση σε αρχεία · File access',
            serverModel.fileOk,
            () => serverModel.toggleFile(),
          ),
          _CheckRow(
            'Ειδοποιήσεις · Notifications',
            _notificationOk,
            () async {
              await serverModel.checkRequestNotificationPermission();
              await _refresh();
            },
          ),
          _CheckRow(
            'Εμφάνιση πάνω από άλλες εφαρμογές · Display over apps',
            _overlayOk,
            _requestOverlay,
          ),
          _CheckRow(
            'Χωρίς όριο μπαταρίας · Ignore battery optimisation',
            _batteryOk,
            _requestBattery,
          ),
          _CheckRow(
            'Εκκίνηση με τη συσκευή · Start on boot',
            _startOnBootOk,
            _enableStartOnBoot,
          ),
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _kBlue.withOpacity(0.06),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: _kBlue.withOpacity(0.25)),
            ),
            child: Row(children: [
              const Icon(Icons.privacy_tip_outlined, color: _kBlue, size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Συνδεόμαστε μόνο όταν μας το ζητήσετε. · '
                  'We connect only when you ask us to.',
                  style: hint,
                ),
              ),
            ]),
          ),
        ],
      ),
    );
  }

  Widget _intro(TextStyle hint) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Για να σας βοηθήσουμε, πατήστε κάθε γραμμή παρακάτω και δώστε την '
          'άδεια που ζητά η συσκευή. Όταν γίνουν όλες πράσινες, τηλεφωνήστε μας '
          'στο $kExelixisPhone και πείτε μας τον αριθμό (ID) που βλέπετε.',
          style: hint,
        ),
        const SizedBox(height: 10),
        Text(
          'To get help, tap each row below and allow the permission the device '
          'asks for. When they are all green, call us on $kExelixisPhone and '
          'tell us the number (ID) shown on the share-screen page.',
          style: hint,
        ),
      ],
    );
  }
}

const kExelixisPhone = '2615 00 2000';

class _CheckRow extends StatelessWidget {
  const _CheckRow(this.label, this.isOk, this.onTap);

  final String label;
  final bool isOk;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: isOk ? null : onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(children: [
          Icon(
            isOk ? Icons.check_circle : Icons.radio_button_unchecked,
            color: isOk ? Colors.green : Colors.grey,
            size: 22,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(label,
                style: TextStyle(
                    fontSize: 14,
                    color: Theme.of(context).textTheme.bodyLarge?.color)),
          ),
          if (!isOk)
            const Text('Ρύθμιση ›',
                style: TextStyle(color: _kBlue, fontSize: 13)),
        ]),
      ),
    );
  }
}
