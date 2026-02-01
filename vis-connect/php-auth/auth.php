<?php

// Initialization 
//
$authorizeURL = "https://iam.viessmann.com/idp/v3/authorize";
$tokenURL = "https://iam.viessmann.com/idp/v3/token";
$client_id = "Your_Customer_ID"; // API Key
$code_verifier = "YOUR CODE VERIFIER";
// PKCE (S256): code_challenge is derived from code_verifier:
//   code_challenge = BASE64URL-ENCODE(SHA256(code_verifier))
$code_challenge = rtrim(strtr(base64_encode(hash('sha256', $code_verifier, true)), '+/', '-_'), '=');
$callback_uri = "http://localhost:4200/";
$user = "Your_Email"; // The same as used for Vicare 
$pwd = "Your_Password"; // The same as used for Vicare 

// Code parameters 
//
$url = "$authorizeURL?client_id=$client_id&code_challenge=$code_challenge&code_challenge_method=S256&scope=IoT%20User&redirect_uri=$callback_uri&response_type=code";
$header = array("Content-Type: application/x-www-form-urlencoded");

$curloptions = array(
    CURLOPT_URL => $url,
    CURLOPT_HTTPHEADER => $header,
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_USERPWD => "$user:$pwd",
    CURLOPT_HTTPAUTH => CURLAUTH_BASIC,
    CURLOPT_POST => true,
);

// Call Curl Code 
//
$curl = curl_init();
curl_setopt_array($curl, $curloptions);
$response = curl_exec($curl);
curl_close($curl);

// Code Extraction 
//
$matches = array();
$pattern = '/code=(.*)"/';
if (preg_match_all($pattern, $response, $matches)) {
    $code = $matches[1][0];
} else {
    exit("Erreur"."\n");
}

// Token Settings 
//
$url = "$tokenURL?grant_type=authorization_code&code_verifier=$code_verifier&client_id=$client_id&redirect_uri=$callback_uri&code=$code";
$header = array("Content-Type: application/x-www-form-urlencoded");

$curloptions = array(
    CURLOPT_URL => $url,
    CURLOPT_HTTPHEADER => $header,
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPAUTH => CURLAUTH_BASIC,
    CURLOPT_POST => true,
);

// Call Curl Token 
//
$curl = curl_init();
curl_setopt_array($curl, $curloptions);
$response = curl_exec($curl);
curl_close($curl);

// Token extraction 
//
$json = json_decode($response, true);
$token = $json['access_token'];

// Read user data 
//
$url = "https://api.viessmann.com/users/v1/users/me?sections=identity";
$header = array("Authorization: Bearer $token");

$curloptions = array(
    CURLOPT_URL => $url,
    CURLOPT_HTTPHEADER => $header,
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPAUTH => CURLAUTH_BASIC,
);

// Data Curl Call 
//
$curl = curl_init();
curl_setopt_array($curl, $curloptions);
$response = curl_exec($curl);
curl_close($curl);

echo($response);