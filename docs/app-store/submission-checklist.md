# Council Mac App Store 提交流程

## 账号侧准备

1. 加入有效的 Apple Developer Program。
2. 在 Certificates, Identifiers & Profiles 注册 Bundle ID `io.council-lab.desktop`。
3. 创建 Mac App Distribution 证书、Mac Installer Distribution 证书和 Mac App Store distribution provisioning profile，并安装证书及私钥。
4. 在 App Store Connect 创建 macOS App 记录，Bundle ID 必须完全一致。
5. 准备公开的支持 URL、隐私政策 URL、审核联系人、分类、年龄分级和截图。

## 生产构建

```zsh
COUNCIL_APP_STORE_MODE=production \
COUNCIL_APP_SIGN_IDENTITY="Mac App Distribution: YOUR NAME (TEAMID)" \
COUNCIL_INSTALLER_SIGN_IDENTITY="Mac Installer Distribution: YOUR NAME (TEAMID)" \
COUNCIL_PROVISIONING_PROFILE="/absolute/path/Council_App_Store.provisionprofile" \
./packaging/build-macos-app-store.sh ./artifacts/app-store
```

不要用 preview 包上传。文件名含 `preview-NOT-FOR-UPLOAD` 的包只有 ad-hoc 应用签名和未签名 installer，用于本机沙盒验证。

## 上传与提交

使用 Transporter 登录 App Store Connect 账号，将生产 `.pkg` 拖入并交付。也可使用具有 App Manager 或 Developer 权限的 App Store Connect API Key：

```zsh
xcrun altool --validate-app --type macos --file ./artifacts/app-store/Council-v0.17.0-Mac-App-Store.pkg --apiKey YOUR_KEY_ID --apiIssuer YOUR_ISSUER_ID
xcrun altool --upload-app --type macos --file ./artifacts/app-store/Council-v0.17.0-Mac-App-Store.pkg --apiKey YOUR_KEY_ID --apiIssuer YOUR_ISSUER_ID
```

上传处理完成后，在 App Store Connect 版本页选择该 build，填写出口合规、内容权利、App 隐私、年龄分级和审核备注，添加审核联系人后点击“添加以供审核”，再提交审核。

## 提交前核对

- `CFBundleVersion` 高于此前所有上传 build。
- `.pkg` 的签名和 Bundle ID 与 App Store Connect 记录一致。
- App Store 构建只监听 `127.0.0.1`，不开放 LAN。
- Mock 路径不需要账号、密钥或付费调用。
- 隐私政策 URL 可在未登录状态访问。
- 截图展示真实产品界面，不包含开发数据、密钥或误导性 Apple 背书。
- 医疗、法律和金融文案明确是决策支持，并要求合格专业人士确认。
